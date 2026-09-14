"""Reject unusable cameras from deterministic semantic passes before paid refinement."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, UnidentifiedImageError

from v365_archviz.artifacts import atomic_write
from v365_archviz.domain.scene import CanonicalScene, SemanticRole
from v365_archviz.domain.workflow import ViewRole, ViewSet
from v365_archviz.errors import InvalidModelError

FOCUS_ROLES = frozenset({"main_shed", "office_block", "roof", "primary_facade", "design_detail"})
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
FOREGROUND_OCCLUDER_ROLES = frozenset({"vehicle"})
MAXIMUM_CENTRAL_OCCLUDER_COVERAGE = 0.12

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
                    "central_entourage_occlusion": central_occluder,
                    "thresholds": {
                        "minimum_focus": minimum_focus,
                        "maximum_focus": maximum_focus,
                        "minimum_circulation": (
                            minimum_circulation if circulation_authored else 0.0
                        ),
                        "maximum_central_entourage_occlusion": (MAXIMUM_CENTRAL_OCCLUDER_COVERAGE),
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
