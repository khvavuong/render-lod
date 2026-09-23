"""Reject unusable cameras from deterministic semantic passes before paid refinement."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, UnidentifiedImageError

from v365_archviz.application.camera_framing import projected_frame_union
from v365_archviz.artifacts import atomic_write
from v365_archviz.domain.scene import CanonicalScene, SemanticRole
from v365_archviz.domain.workflow import ViewRole, ViewSet
from v365_archviz.errors import InvalidModelError

# A LOD200 model draws the building as walls and roof planes rather than as one
# mass, and at eye level the walls are the only part of it in frame. Leaving
# them out measured the subject at under one per cent of the image and rejected
# every camera before generation.
FOCUS_ROLES = frozenset(
    {
        "main_shed",
        "office_block",
        "roof",
        "canopy",
        "envelope_panel",
        "loading_dock",
        "primary_facade",
        "design_detail",
    }
)
CIRCULATION_ROLES = frozenset(
    {
        "site_road",
        "sidewalk",
        "service_yard",
        "parking",
        "loading_zone",
        "main_entrance",
        "secondary_entrance",
    }
)
CONTEXT_ROLES = frozenset({"context_building", "context_landscape", "landscape_zone"})
SITE_PLAN_ROLES = frozenset(
    {
        "site_ground",
        "site_road",
        "sidewalk",
        "service_yard",
        "parking",
        "loading_zone",
        "main_entrance",
        "secondary_entrance",
        "landscape_zone",
        "site_boundary",
    }
)
AERIAL_ROLES = frozenset({ViewRole.OVERALL, ViewRole.DETAIL})
MINIMUM_AERIAL_SITE_PLAN_COVERAGE = 0.12
MINIMUM_AERIAL_VISIBLE_SURFACE_ROLES = 3
MINIMUM_AERIAL_DEPRESSION_DEGREES = 18.0
FOREGROUND_OCCLUDER_ROLES = frozenset({"vehicle"})
MAXIMUM_CENTRAL_OCCLUDER_COVERAGE = 0.12
#: How much of what the geometry predicts must survive into the render.
#:
#: This used to be a share of the frame per role, which cannot be right for two
#: models at once. A service yard is two thousand square metres of ground and a
#: dock door is sixteen; asking both for one percent of a frame asks the door to
#: be photographed from six metres, and refuses a correctly framed logistics
#: view of a model that authored eighteen doors and no apron. It also refused a
#: LOD100 context view that was pointed straight at its gate, because a truck
#: gate at a hundred metres is half of one tenth of a percent of the frame and
#: nothing can change that but walking closer.
#:
#: What both can be asked is that they show up in something like the proportion
#: the geometry says they should. Measured across the two real models the ratio
#: runs from 0.12 — an aerial whose planting is mostly under its own trees — to
#: 1.84, where the site grammar paints more ground than the model authored. The
#: failures it has to keep catching sit at 0.00 to 0.03: an office block behind
#: the shed it belongs to, an entrance hidden by a neighbour.
MINIMUM_VISIBLE_FRACTION_OF_PREDICTED = 0.10

ROLE_TARGETS: dict[ViewRole, frozenset[str]] = {
    ViewRole.OVERALL: frozenset({"site_road", "landscape_zone", "main_entrance"}),
    ViewRole.CONTEXT: frozenset({"main_entrance", "secondary_entrance"}),
    # A dock door is what a logistics view is of. A LOD200 model authors the
    # doors and leaves the apron to the site drawing, so a gate that accepts
    # only ground rejects every such model however well the view is framed.
    ViewRole.HERO: frozenset({"loading_zone", "service_yard", "loading_dock"}),
    ViewRole.DETAIL: frozenset({"site_road", "service_yard", "parking", "landscape_zone"}),
    ViewRole.OFFICE_HERO: frozenset({"office_block", "design_detail", "primary_facade"}),
    ViewRole.LOADING_DETAIL: frozenset(
        {
            "main_entrance",
            "office_block",
            "loading_zone",
            "loading_dock",
            "design_detail",
            "primary_facade",
        }
    ),
}

# Deliberately lenient hard-reject thresholds. They catch empty, excessively distant, or badly
# cropped cameras; bid-quality composition remains a human/aesthetic gate until benchmark tuning.
ROLE_THRESHOLDS: dict[ViewRole, tuple[float, float, float]] = {
    ViewRole.OVERALL: (0.06, 0.72, 0.02),
    ViewRole.CONTEXT: (0.08, 0.88, 0.015),
    ViewRole.HERO: (0.12, 0.90, 0.04),
    ViewRole.DETAIL: (0.06, 0.75, 0.015),
    ViewRole.OFFICE_HERO: (0.15, 0.92, 0.005),
    # At pedestrian eye level, a legible gate/fence opening can occupy less image area
    # than a drone-visible yard. Count authored entrances as circulation and keep the
    # threshold high enough to reject a hidden or cropped access point.
    ViewRole.LOADING_DETAIL: (0.12, 0.90, 0.01),
}


def _aspect_ratio(notation: str) -> float:
    """A camera states its aspect as `16:9`; the projection wants the number."""

    try:
        width, height = (float(part) for part in notation.split(":", 1))
    except ValueError:
        return 16 / 9
    return width / height if height > 0 else 16 / 9


@dataclass(frozen=True, slots=True)
class ConditioningValidationArtifacts:
    report_path: Path
    passed: bool
    failed_view_ids: tuple[str, ...]


class ValidateConditioningViewSet:
    """Measure camera occupancy from an unstyled semantic-ID render."""

    def execute(
        self,
        scene_path: Path,
        view_set_path: Path,
        render_root: Path,
        output_path: Path | None = None,
        *,
        color_tolerance: int = 36,
    ) -> ConditioningValidationArtifacts:
        try:
            scene = CanonicalScene.model_validate_json(scene_path.read_text(encoding="utf-8"))
            view_set = ViewSet.model_validate_json(view_set_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise InvalidModelError(f"cannot load conditioning QA contracts: {exc}") from exc

        authored_roles = {element.semantic_role for element in scene.elements}
        authored_role_names = {role.value for role in authored_roles}
        circulation_authored = bool(
            authored_roles
            & {
                SemanticRole.SITE_ROAD,
                SemanticRole.SIDEWALK,
                SemanticRole.SERVICE_YARD,
                SemanticRole.PARKING,
                SemanticRole.LOADING_ZONE,
            }
        )
        views: list[dict[str, Any]] = []
        failed: list[str] = []
        for camera in view_set.cameras:
            view_root = render_root / camera.view_id
            coverage = self._semantic_coverage(
                view_root / "semantic.png",
                view_root / "semantic_id_manifest.json",
                color_tolerance,
            )
            central_coverage = self._semantic_coverage(
                view_root / "semantic.png",
                view_root / "semantic_id_manifest.json",
                color_tolerance,
                crop=(0.25, 0.20, 0.75, 0.80),
            )
            focus = sum(coverage.get(role, 0.0) for role in FOCUS_ROLES)
            circulation = sum(coverage.get(role, 0.0) for role in CIRCULATION_ROLES)
            context = sum(coverage.get(role, 0.0) for role in CONTEXT_ROLES)
            site_plan = sum(coverage.get(role, 0.0) for role in SITE_PLAN_ROLES)
            visible_site_roles = sorted(
                role
                for role in SITE_PLAN_ROLES & authored_role_names
                if coverage.get(role, 0.0) >= 0.001
            )
            horizontal_distance = math.hypot(
                camera.position[0] - camera.target[0],
                camera.position[1] - camera.target[1],
            )
            depression_degrees = math.degrees(
                math.atan2(camera.position[2] - camera.target[2], horizontal_distance)
            )
            available_role_targets = ROLE_TARGETS[camera.role] & authored_role_names
            role_target_coverage = sum(coverage.get(role, 0.0) for role in available_role_targets)
            predicted_role_target = projected_frame_union(
                camera.position,
                camera.target,
                [
                    (element.bounding_box.minimum, element.bounding_box.maximum)
                    for element in scene.elements
                    if element.semantic_role.value in available_role_targets
                ],
                camera.focal_length_mm,
                sensor_width_mm=camera.sensor_width_mm,
                aspect_ratio=_aspect_ratio(camera.aspect_ratio),
            )
            central_occluder = sum(
                central_coverage.get(role, 0.0) for role in FOREGROUND_OCCLUDER_ROLES
            )
            minimum_focus, maximum_focus, minimum_circulation = ROLE_THRESHOLDS[camera.role]
            failures = []
            if focus < minimum_focus:
                failures.append("focus_subject_too_small_or_missing")
            if focus > maximum_focus:
                failures.append("focus_subject_excessively_cropped")
            if circulation_authored and circulation < minimum_circulation:
                failures.append("authored_circulation_not_visible")
            if central_occluder > MAXIMUM_CENTRAL_OCCLUDER_COVERAGE:
                failures.append("foreground_entourage_obstructs_subject")
            minimum_role_target = MINIMUM_VISIBLE_FRACTION_OF_PREDICTED * predicted_role_target
            if available_role_targets:
                if predicted_role_target <= 0.0:
                    # Nothing to do with occlusion: the camera is not pointed at it.
                    failures.append("camera_role_target_not_in_frame")
                elif role_target_coverage < minimum_role_target:
                    failures.append("camera_role_target_not_visible")
            authored_site_underlay = SemanticRole.SITE_GROUND in authored_roles
            if camera.role in AERIAL_ROLES and authored_site_underlay:
                if site_plan < MINIMUM_AERIAL_SITE_PLAN_COVERAGE:
                    failures.append("aerial_site_plan_not_sufficiently_visible")
                if len(visible_site_roles) < MINIMUM_AERIAL_VISIBLE_SURFACE_ROLES:
                    failures.append("aerial_site_surface_layers_not_legible")
                if depression_degrees < MINIMUM_AERIAL_DEPRESSION_DEGREES:
                    failures.append("aerial_camera_angle_too_shallow")
            status = "pass" if not failures else "fail"
            if failures:
                failed.append(camera.view_id)
            views.append(
                {
                    "view_id": camera.view_id,
                    "role": camera.role.value,
                    "status": status,
                    "focus_coverage": focus,
                    "circulation_coverage": circulation,
                    "context_coverage": context,
                    "site_plan_coverage": site_plan,
                    "visible_site_roles": visible_site_roles,
                    "camera_depression_degrees": depression_degrees,
                    "role_target_coverage": role_target_coverage,
                    "predicted_role_target_coverage": predicted_role_target,
                    "available_role_targets": sorted(available_role_targets),
                    "central_entourage_occlusion": central_occluder,
                    "thresholds": {
                        "minimum_focus": minimum_focus,
                        "maximum_focus": maximum_focus,
                        "minimum_circulation": (
                            minimum_circulation if circulation_authored else 0.0
                        ),
                        "maximum_central_entourage_occlusion": (MAXIMUM_CENTRAL_OCCLUDER_COVERAGE),
                        "minimum_role_target_coverage": (
                            minimum_role_target if available_role_targets else 0.0
                        ),
                        "minimum_aerial_site_plan_coverage": (
                            MINIMUM_AERIAL_SITE_PLAN_COVERAGE
                            if camera.role in AERIAL_ROLES and authored_site_underlay
                            else 0.0
                        ),
                        "minimum_aerial_visible_surface_roles": (
                            MINIMUM_AERIAL_VISIBLE_SURFACE_ROLES
                            if camera.role in AERIAL_ROLES and authored_site_underlay
                            else 0
                        ),
                        "minimum_aerial_depression_degrees": (
                            MINIMUM_AERIAL_DEPRESSION_DEGREES
                            if camera.role in AERIAL_ROLES and authored_site_underlay
                            else 0.0
                        ),
                    },
                    "findings": failures,
                }
            )

        target = output_path or render_root / "conditioning_qa.json"
        report = {
            "schema_version": "1.0.0",
            "scope": "pre_generation_camera_semantic_coverage",
            "status": "pass" if not failed else "fail",
            "circulation_authored": circulation_authored,
            "views": views,
            "threshold_status": "benchmark_hypothesis",
            "note": (
                "A pass rejects gross camera failures before paid generation; it does not replace "
                "aesthetic review or prove semantic fidelity of the refined image."
            ),
        }
        atomic_write(
            target,
            json.dumps(report, ensure_ascii=False, indent=2).encode("utf-8") + b"\n",
        )
        return ConditioningValidationArtifacts(target, not failed, tuple(failed))

    @staticmethod
    def _semantic_coverage(
        image_path: Path,
        manifest_path: Path,
        color_tolerance: int,
        crop: tuple[float, float, float, float] | None = None,
    ) -> dict[str, float]:
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            roles = manifest["roles"]
            names = [str(item["semantic_role"]) for item in roles]
            # int32 is intentional: squaring an RGB delta can overflow int16 and silently
            # classify bright sky/background pixels as dark circulation surfaces.
            palette = np.asarray([item["srgb8"] for item in roles], dtype=np.int32)
            with Image.open(image_path) as source:
                image = np.asarray(source.convert("RGB"), dtype=np.int32)
        except (OSError, KeyError, TypeError, ValueError, UnidentifiedImageError) as exc:
            raise InvalidModelError(f"cannot read semantic coverage inputs: {exc}") from exc
        if palette.ndim != 2 or palette.shape[1] != 3 or not len(palette):
            raise InvalidModelError("semantic ID manifest contains no valid RGB role colors")
        if crop is not None:
            height, width = image.shape[:2]
            left, top, right, bottom = crop
            image = image[
                round(height * top) : round(height * bottom),
                round(width * left) : round(width * right),
            ]
        pixels = image.reshape(-1, 3)
        distances = np.sum((pixels[:, None, :] - palette[None, :, :]) ** 2, axis=2)
        nearest = np.argmin(distances, axis=1)
        accepted = np.min(distances, axis=1) <= color_tolerance**2
        total = max(1, len(pixels))
        return {
            name: float(np.count_nonzero((nearest == index) & accepted)) / total
            for index, name in enumerate(names)
        }
