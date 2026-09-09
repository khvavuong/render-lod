"""Deterministic standard camera planning for an industrial campus."""

from __future__ import annotations

from itertools import pairwise
from pathlib import Path

from v365_archviz.artifacts import atomic_write
from v365_archviz.domain.design import BuildingTreatment, DesignDNA
from v365_archviz.domain.scene import CanonicalScene, SceneElement, SemanticRole
from v365_archviz.domain.workflow import Camera, ViewRole, ViewSet


def _architectural_elements(scene: CanonicalScene) -> list[SceneElement]:
    candidates = [
        element
        for element in scene.elements
        if element.bounding_box.maximum[2] - element.bounding_box.minimum[2] >= 3.0
    ]
    return candidates or list(scene.elements)


def _height(element: SceneElement) -> float:
    return element.bounding_box.maximum[2] - element.bounding_box.minimum[2]


def _bounds_for(
    elements: list[SceneElement],
) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    minimum = tuple(
        min(element.bounding_box.minimum[index] for element in elements) for index in range(3)
    )
    maximum = tuple(
        max(element.bounding_box.maximum[index] for element in elements) for index in range(3)
    )
    return minimum, maximum  # type: ignore[return-value]


def _axis_point(
    center: tuple[float, float, float],
    long_axis: int,
    long_offset: float,
    cross_offset: float,
    z: float,
) -> tuple[float, float, float]:
    """Map project-relative longitudinal/cross offsets back to world coordinates."""

    if long_axis == 0:
        return center[0] + long_offset, center[1] + cross_offset, z
    return center[0] + cross_offset, center[1] + long_offset, z


def _corridor_cross_coordinate(design: DesignDNA | None, long_axis: int, fallback: float) -> float:
    """Find the centre of the clearest gap between parallel roof assemblies."""

    if design is None or len(design.roof_assemblies) < 2:
        return fallback
    cross_axis = 1 - long_axis
    ordered = sorted(
        design.roof_assemblies,
        key=lambda assembly: (
            assembly.bounding_box.minimum[cross_axis]
            + assembly.bounding_box.maximum[cross_axis]
        )
        / 2,
    )
    candidates: list[tuple[float, float]] = []
    for lower, upper in pairwise(ordered):
        lower_edge = lower.bounding_box.maximum[cross_axis]
        upper_edge = upper.bounding_box.minimum[cross_axis]
        gap = upper_edge - lower_edge
        if gap > 0:
            candidates.append((gap, (lower_edge + upper_edge) / 2))
    return max(candidates, default=(0.0, fallback))[1]


def _preferred_long_axis(design: DesignDNA | None, fallback: int) -> int:
    """Infer building orientation from roof assemblies, not the campus envelope.

    Two parallel sheds can make the overall site longer across the buildings than
    along either shed.  Using the site envelope in that case points corridor views
    through a building instead of along the open space between the rows.
    """

    if design is None or not design.roof_assemblies:
        return fallback
    votes = [0.0, 0.0]
    for assembly in design.roof_assemblies:
        extent_x = assembly.bounding_box.maximum[0] - assembly.bounding_box.minimum[0]
        extent_y = assembly.bounding_box.maximum[1] - assembly.bounding_box.minimum[1]
        geometry_long_axis = 0 if extent_x >= extent_y else 1
        roof_long_axis = (
            geometry_long_axis
            if assembly.roof.ridge_orientation == "long_axis"
            else 1 - geometry_long_axis
        )
        votes[roof_long_axis] += max(extent_x, extent_y)
    return 0 if votes[0] >= votes[1] else 1


class PlanStandardCameras:
    def execute(self, scene_path: Path, design_dna_path: Path | None = None) -> ViewSet:
        scene = CanonicalScene.model_validate_json(scene_path.read_text(encoding="utf-8"))
        design = None
        focus_ids: set[str] = set()
        if design_dna_path is not None:
            design = DesignDNA.model_validate_json(design_dna_path.read_text(encoding="utf-8"))
            focus_ids = {
                building.building_id
                for building in design.buildings
                if building.treatment is BuildingTreatment.FOCUS
            }
        architectural = [
            element
            for element in _architectural_elements(scene)
            if element.semantic_role in {SemanticRole.MAIN_SHED, SemanticRole.OFFICE_BLOCK}
            and (not focus_ids or element.scene_element_id in focus_ids)
        ] or _architectural_elements(scene)
        minimum, maximum = _bounds_for(architectural)
        center = (
            (minimum[0] + maximum[0]) / 2,
            (minimum[1] + maximum[1]) / 2,
            (minimum[2] + maximum[2]) / 2,
        )
        span_x = maximum[0] - minimum[0]
        span_y = maximum[1] - minimum[1]
        span = max(span_x, span_y)
        site_long_axis = 0 if span_x >= span_y else 1
        long_axis = _preferred_long_axis(design, site_long_axis)
        cross_axis = 1 - long_axis
        long_span = (span_x, span_y)[long_axis]
        cross_span = (span_x, span_y)[cross_axis]
        long_min = minimum[long_axis]
        height = maximum[2] - minimum[2]
        ground_target_z = minimum[2] + height * 0.42
        aerial_target_z = minimum[2] + height * 0.25
        corridor_cross = _corridor_cross_coordinate(design, long_axis, center[cross_axis])
        site_roles = {
            SemanticRole.SITE_ROAD,
            SemanticRole.SIDEWALK,
            SemanticRole.SERVICE_YARD,
            SemanticRole.PARKING,
            SemanticRole.MAIN_ENTRANCE,
            SemanticRole.SECONDARY_ENTRANCE,
            SemanticRole.LANDSCAPE_ZONE,
            SemanticRole.SITE_BOUNDARY,
        }
        site_elements = [
            element for element in scene.elements if element.semantic_role in site_roles
        ]
        site_minimum, site_maximum = _bounds_for([*architectural, *site_elements])
        site_center = (
            (site_minimum[0] + site_maximum[0]) / 2,
            (site_minimum[1] + site_maximum[1]) / 2,
            (site_minimum[2] + site_maximum[2]) / 2,
        )
        site_span_x = site_maximum[0] - site_minimum[0]
        site_span_y = site_maximum[1] - site_minimum[1]
        site_long_span = (site_span_x, site_span_y)[long_axis]
        site_span = max(site_span_x, site_span_y)

        def point(long_offset: float, cross_offset: float, z: float) -> tuple[float, float, float]:
            return _axis_point(center, long_axis, long_offset, cross_offset, z)

        def corridor_point(long_coordinate: float, z: float) -> tuple[float, float, float]:
            coordinate = [center[0], center[1], z]
            coordinate[long_axis] = long_coordinate
            coordinate[cross_axis] = corridor_cross
            return tuple(coordinate)  # type: ignore[return-value]

        cameras = (
            Camera(
                view_id="view-01",
                role=ViewRole.OVERALL,
                position=_axis_point(
                    site_center,
                    long_axis,
                    -site_long_span * 1.45,
                    -site_span * 1.25,
                    maximum[2] + site_span * 1.05,
                ),
                target=(site_center[0], site_center[1], minimum[2] + height * 0.15),
                focal_length_mm=46,
                sensor_width_mm=36,
                aspect_ratio="16:9",
            ),
            Camera(
                view_id="view-02",
                role=ViewRole.CONTEXT,
                position=point(long_span * 1.18, span * 1.02, maximum[2] + span * 0.68),
                target=(center[0], center[1], aerial_target_z),
                focal_length_mm=44,
                sensor_width_mm=36,
                aspect_ratio="16:9",
            ),
            Camera(
                view_id="view-03",
                role=ViewRole.HERO,
                position=corridor_point(
                    long_min - max(24.0, long_span * 0.10),
                    minimum[2] + max(7.0, height * 0.48),
                ),
                target=corridor_point(long_min + long_span * 0.38, height * 0.32),
                focal_length_mm=36,
                sensor_width_mm=36,
                aspect_ratio="16:9",
            ),
            Camera(
                view_id="view-04",
                role=ViewRole.DETAIL,
                position=point(
                    -long_span * 0.46,
                    -(cross_span / 2 + span * 0.48),
                    minimum[2] + max(30.0, height * 2.5),
                ),
                target=point(-long_span * 0.08, -cross_span * 0.38, ground_target_z),
                focal_length_mm=42,
                sensor_width_mm=36,
                aspect_ratio="16:9",
            ),
            Camera(
                view_id="view-05",
                role=ViewRole.OFFICE_HERO,
                position=point(
                    long_span * 0.88,
                    cross_span / 2 + span * 0.62,
                    minimum[2] + max(36.0, height * 3.0),
                ),
                target=point(long_span * 0.12, cross_span * 0.38, ground_target_z),
                focal_length_mm=46,
                sensor_width_mm=36,
                aspect_ratio="16:9",
            ),
            Camera(
                view_id="view-06",
                role=ViewRole.LOADING_DETAIL,
                position=corridor_point(long_min + long_span * 0.10, minimum[2] + 1.65),
                target=corridor_point(
                    long_min + long_span * 0.40,
                    minimum[2] + min(3.2, height * 0.3),
                ),
                focal_length_mm=32,
                sensor_width_mm=36,
                aspect_ratio="16:9",
            ),
        )
        revision_key = (
            scene.source.source_sha256[:16]
            if scene.source.source_sha256
            else scene.source.version_id.replace(":", "-")
        )
        design_revision = f"scene-{revision_key}"
        if design is not None:
            design_revision = design.design_revision
        view_set = ViewSet(
            view_set_id=f"{revision_key}-{design_revision}-standard-v6",
            design_revision=design_revision,
            cameras=cameras,
        )
        output = (
            design_dna_path.parent / "view_set.json"
            if design_dna_path is not None
            else scene_path.parent / "view_set.json"
        )
        atomic_write(output, view_set.model_dump_json(indent=2).encode() + b"\n")
        return view_set
