"""Deterministic standard camera planning for an industrial campus."""

from __future__ import annotations

import math
from itertools import pairwise
from pathlib import Path

from v365_archviz.artifacts import atomic_write
from v365_archviz.domain.design import BuildingTreatment, DesignDNA, FacadeDesign, LoadingDock
from v365_archviz.domain.scene import CanonicalScene, SceneElement, SceneSurface, SemanticRole
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


def _fit_camera_to_bounds(
    minimum: tuple[float, float, float],
    maximum: tuple[float, float, float],
    target: tuple[float, float, float],
    camera_direction: tuple[float, float, float],
    *,
    focal_length_mm: float,
    sensor_width_mm: float,
    aspect_ratio: float = 16 / 9,
    frame_margin: float = 0.88,
) -> tuple[float, float, float]:
    """Place a camera so all eight world-space bounds corners fit its perspective frame."""

    def normalize(vector: tuple[float, float, float]) -> tuple[float, float, float]:
        length = math.sqrt(sum(component * component for component in vector))
        if length <= 1e-9:
            raise ValueError("camera direction must be non-zero")
        return tuple(component / length for component in vector)  # type: ignore[return-value]

    def dot(first: tuple[float, float, float], second: tuple[float, float, float]) -> float:
        return sum(a * b for a, b in zip(first, second, strict=True))

    def cross(
        first: tuple[float, float, float], second: tuple[float, float, float]
    ) -> tuple[float, float, float]:
        return (
            first[1] * second[2] - first[2] * second[1],
            first[2] * second[0] - first[0] * second[2],
            first[0] * second[1] - first[1] * second[0],
        )

    from_target = normalize(camera_direction)
    forward = (-from_target[0], -from_target[1], -from_target[2])
    right = normalize(cross(forward, (0.0, 0.0, 1.0)))
    camera_up = normalize(cross(right, forward))
    horizontal_tangent = sensor_width_mm / (2 * focal_length_mm)
    vertical_tangent = horizontal_tangent / aspect_ratio
    distance = 0.0
    for x in (minimum[0], maximum[0]):
        for y in (minimum[1], maximum[1]):
            for z in (minimum[2], maximum[2]):
                delta = (x - target[0], y - target[1], z - target[2])
                forward_offset = dot(delta, forward)
                horizontal_need = (
                    abs(dot(delta, right)) / (horizontal_tangent * frame_margin) - forward_offset
                )
                vertical_need = (
                    abs(dot(delta, camera_up)) / (vertical_tangent * frame_margin) - forward_offset
                )
                distance = max(distance, horizontal_need, vertical_need)
    return (
        target[0] + from_target[0] * distance,
        target[1] + from_target[1] * distance,
        target[2] + from_target[2] * distance,
    )


def _corridor_cross_coordinate(design: DesignDNA | None, long_axis: int) -> float | None:
    """Find the centre of the clearest gap between parallel roof assemblies."""

    if design is None or len(design.roof_assemblies) < 2:
        return None
    cross_axis = 1 - long_axis
    ordered = sorted(
        design.roof_assemblies,
        key=lambda assembly: (
            (assembly.bounding_box.minimum[cross_axis] + assembly.bounding_box.maximum[cross_axis])
            / 2
        ),
    )
    candidates: list[tuple[float, float]] = []
    for lower, upper in pairwise(ordered):
        lower_edge = lower.bounding_box.maximum[cross_axis]
        upper_edge = upper.bounding_box.minimum[cross_axis]
        gap = upper_edge - lower_edge
        if gap > 0:
            candidates.append((gap, (lower_edge + upper_edge) / 2))
    return max(candidates)[1] if candidates else None


def _authored_access_cross_coordinate(
    scene: CanonicalScene,
    long_axis: int,
    architectural_minimum: tuple[float, float, float],
    architectural_maximum: tuple[float, float, float],
) -> float | None:
    """Select an authored circulation strip beside a single building row.

    Loading yards take priority over roads because they expose operational doors without placing
    the camera outside the site fence. Only strips with meaningful longitudinal overlap qualify.
    """

    cross_axis = 1 - long_axis
    long_min = architectural_minimum[long_axis]
    long_max = architectural_maximum[long_axis]
    long_span = long_max - long_min
    candidates: list[tuple[int, float, float]] = []
    priorities = {
        SemanticRole.LOADING_ZONE: 0,
        SemanticRole.SERVICE_YARD: 1,
        SemanticRole.SITE_ROAD: 2,
    }
    for element in scene.elements:
        priority = priorities.get(element.semantic_role)
        if priority is None:
            continue
        bounds = element.bounding_box
        overlap = max(
            0.0,
            min(long_max, bounds.maximum[long_axis]) - max(long_min, bounds.minimum[long_axis]),
        )
        if overlap < long_span * 0.18:
            continue
        cross_center = (bounds.minimum[cross_axis] + bounds.maximum[cross_axis]) / 2
        distance = min(
            abs(cross_center - architectural_minimum[cross_axis]),
            abs(cross_center - architectural_maximum[cross_axis]),
        )
        candidates.append((priority, distance, cross_center))
    return min(candidates)[2] if candidates else None


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


def _arrival_shot(
    scene: CanonicalScene,
    focus_minimum: tuple[float, float, float],
    focus_maximum: tuple[float, float, float],
    site_center: tuple[float, float, float],
    site_span: float,
) -> tuple[tuple[float, float, float], tuple[float, float, float]] | None:
    """Place a human-eye camera on an authored entrance, looking into the site.

    The entrance geometry is the only reliable generic source for a gate-facing shot.
    Deriving the direction from the site centre avoids project-specific axis assumptions.
    """

    entrances = [
        element for element in scene.elements if element.semantic_role is SemanticRole.MAIN_ENTRANCE
    ]
    if not entrances:
        return None
    focus_center = tuple((focus_minimum[index] + focus_maximum[index]) / 2 for index in range(3))
    entrance = min(
        entrances,
        key=lambda element: math.dist(
            (
                (element.bounding_box.minimum[0] + element.bounding_box.maximum[0]) / 2,
                (element.bounding_box.minimum[1] + element.bounding_box.maximum[1]) / 2,
            ),
            (focus_center[0], focus_center[1]),
        ),
    )
    gate_center = (
        (entrance.bounding_box.minimum[0] + entrance.bounding_box.maximum[0]) / 2,
        (entrance.bounding_box.minimum[1] + entrance.bounding_box.maximum[1]) / 2,
    )
    outward = (gate_center[0] - site_center[0], gate_center[1] - site_center[1])
    length = math.hypot(*outward)
    if length <= 1e-6:
        return None
    outward = (outward[0] / length, outward[1] / length)
    # Keep the entrance as the visual axis, but add a restrained lateral offset. A perfectly
    # centred elevation compresses the access road and makes a 12 m truck gate look narrow;
    # this near-frontal approach retains evidence while revealing driveway depth.
    # A distant camera can technically contain a gate while reducing it to a few pixels. Keep a
    # truck-scaled opening prominent enough to read as the actual arrival sequence.
    setback = max(26.0, min(38.0, site_span * 0.13))
    tangent = (-outward[1], outward[0])
    lateral_offset = min(26.0, max(18.0, site_span * 0.09))
    focus_height = focus_maximum[2] - focus_minimum[2]
    position = (
        gate_center[0] + outward[0] * setback + tangent[0] * lateral_offset,
        gate_center[1] + outward[1] * setback + tangent[1] * lateral_offset,
        focus_minimum[2] + 1.75,
    )
    # Aim through the gate toward the nearest point of the focus building. Keeping
    # part of that depth in the target reveals the project behind the entrance while
    # the centred portal remains foreground evidence.
    nearest_focus = (
        min(max(gate_center[0], focus_minimum[0]), focus_maximum[0]),
        min(max(gate_center[1], focus_minimum[1]), focus_maximum[1]),
    )
    target = (
        gate_center[0]
        + (nearest_focus[0] - gate_center[0]) * 0.34
        - tangent[0] * lateral_offset * 0.32,
        gate_center[1]
        + (nearest_focus[1] - gate_center[1]) * 0.34
        - tangent[1] * lateral_offset * 0.32,
        focus_minimum[2] + max(3.2, focus_height * 0.24),
    )
    return position, target


def _golden_arrival_shot(
    arrival_shot: tuple[tuple[float, float, float], tuple[float, float, float]] | None,
) -> tuple[tuple[float, float, float], tuple[float, float, float]] | None:
    """Create a closer, asymmetric human-scale marketing view from the authored arrival axis."""

    if arrival_shot is None:
        return None
    position, target = arrival_shot
    delta = (target[0] - position[0], target[1] - position[1])
    distance = math.hypot(*delta)
    if distance <= 1e-6:
        return None
    forward = (delta[0] / distance, delta[1] / distance)
    tangent = (-forward[1], forward[0])
    advance = min(14.0, max(9.0, distance * 0.28))
    lateral = min(9.0, max(5.0, distance * 0.16))
    return (
        (
            position[0] + forward[0] * advance + tangent[0] * lateral,
            position[1] + forward[1] * advance + tangent[1] * lateral,
            position[2],
        ),
        (
            target[0] + forward[0] * min(5.0, distance * 0.1),
            target[1] + forward[1] * min(5.0, distance * 0.1),
            target[2],
        ),
    )


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
        site_long_axis = 0 if span_x >= span_y else 1
        long_axis = _preferred_long_axis(design, site_long_axis)
        cross_axis = 1 - long_axis
        long_span = (span_x, span_y)[long_axis]
        cross_span = (span_x, span_y)[cross_axis]
        long_min = minimum[long_axis]
        height = maximum[2] - minimum[2]
        detected_corridor = _corridor_cross_coordinate(design, long_axis)
        authored_access = _authored_access_cross_coordinate(scene, long_axis, minimum, maximum)
        has_internal_corridor = detected_corridor is not None
        corridor_cross = (
            detected_corridor
            if detected_corridor is not None
            else authored_access
            if authored_access is not None
            else minimum[cross_axis] - max(24.0, cross_span * 0.25)
        )
        corridor_target_cross = (
            corridor_cross
            if has_internal_corridor or authored_access is not None
            else minimum[cross_axis] + min(3.0, cross_span * 0.06)
        )
        access_facade_cross = min(
            (minimum[cross_axis], maximum[cross_axis]),
            key=lambda coordinate: abs(coordinate - corridor_cross),
        )
        site_roles = {
            SemanticRole.SITE_GROUND,
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
        # The two aerial views document the authored masterplan, not only the largest shed.
        # Fit the complete site envelope and use a true downward oblique direction. The former
        # implementation fitted the building, then clamped Z to 40 m; on wide campuses that
        # produced a 7-10 degree grazing view in which the site plan was largely hidden.
        overall_target = (site_center[0], site_center[1], minimum[2] + height * 0.12)
        overall_direction = _axis_point(
            (0.0, 0.0, 0.0),
            long_axis,
            -1.0,
            -0.85,
            0.72,
        )
        overall_position = _fit_camera_to_bounds(
            site_minimum,
            site_maximum,
            overall_target,
            overall_direction,
            focal_length_mm=28.0,
            sensor_width_mm=36.0,
            # A controlled crop gives the project presentation weight while retaining roughly
            # 70-80% of the authored site, matching a commercial hero aerial rather than GIS.
            frame_margin=1.18,
        )
        reverse_overall_direction = _axis_point(
            (0.0, 0.0, 0.0),
            long_axis,
            1.0,
            0.74,
            0.72,
        )
        reverse_overall_target = (site_center[0], site_center[1], minimum[2] + height * 0.18)
        reverse_overall_position = _fit_camera_to_bounds(
            site_minimum,
            site_maximum,
            reverse_overall_target,
            reverse_overall_direction,
            focal_length_mm=28.0,
            sensor_width_mm=36.0,
            frame_margin=1.18,
        )
        arrival_shot = _arrival_shot(
            scene,
            minimum,
            maximum,
            site_center,
            max(site_maximum[0] - site_minimum[0], site_maximum[1] - site_minimum[1]),
        )
        golden_arrival_shot = _golden_arrival_shot(arrival_shot)

        def point(long_offset: float, cross_offset: float, z: float) -> tuple[float, float, float]:
            return _axis_point(center, long_axis, long_offset, cross_offset, z)

        def corridor_point(
            long_coordinate: float, z: float, *, target: bool = False
        ) -> tuple[float, float, float]:
            coordinate = [center[0], center[1], z]
            coordinate[long_axis] = long_coordinate
            coordinate[cross_axis] = corridor_target_cross if target else corridor_cross
            return tuple(coordinate)  # type: ignore[return-value]

        loading_detail_shot: (
            tuple[tuple[float, float, float], tuple[float, float, float]] | None
        ) = None
        loading_human_shot: tuple[tuple[float, float, float], tuple[float, float, float]] | None = (
            None
        )
        reverse_facade_shot: (
            tuple[tuple[float, float, float], tuple[float, float, float]] | None
        ) = None
        office_detail_shot: tuple[tuple[float, float, float], tuple[float, float, float]] | None = (
            None
        )
        facade_detail_shot: tuple[tuple[float, float, float], tuple[float, float, float]] | None = (
            None
        )
        if design is not None:
            surfaces_by_id = {surface.surface_id: surface for surface in scene.surfaces}
            office_candidates = [
                (facade, surfaces_by_id.get(facade.surface_id), facade.office_entrance)
                for building in design.buildings
                if building.treatment is BuildingTreatment.FOCUS
                for facade in building.facades
                if facade.office_entrance is not None
            ]
            if office_candidates:
                _office_facade, office_surface, office_entrance = max(
                    office_candidates,
                    key=lambda candidate: candidate[1].width_m if candidate[1] is not None else 0.0,
                )
                if office_surface is not None and office_entrance is not None:
                    frame = office_surface.frame
                    entrance = tuple(
                        frame.origin[index]
                        + frame.u_axis[index] * (office_entrance.u * office_surface.width_m)
                        for index in range(3)
                    )
                    side = -1.0 if office_entrance.u >= 0.5 else 1.0
                    lateral = min(22.0, max(14.0, office_surface.width_m * 0.16))
                    outward = min(16.0, max(10.0, cross_span * 0.12))
                    office_detail_shot = (
                        (
                            entrance[0]
                            + frame.u_axis[0] * lateral * side
                            + frame.normal[0] * outward,
                            entrance[1]
                            + frame.u_axis[1] * lateral * side
                            + frame.normal[1] * outward,
                            minimum[2] + 1.85,
                        ),
                        (
                            entrance[0],
                            entrance[1],
                            minimum[2] + min(3.6, height * 0.32),
                        ),
                    )
            all_loading_candidates = [
                (facade, surfaces_by_id.get(facade.surface_id), dock, side)
                for building in design.buildings
                if building.treatment is BuildingTreatment.FOCUS
                for facade in building.facades
                for dock in facade.loading_docks
                for side in (-1.0, 1.0)
            ]
            density_factor = {"none": 0.0, "low": 0.65, "medium": 1.0, "high": 1.35}[
                design.presentation.entourage_density
            ]
            ordered_dock_ids = list(
                dict.fromkeys(candidate[2].dock_id for candidate in all_loading_candidates)
            )
            occupied_count = min(
                max(0, len(ordered_dock_ids) - 1), max(1, round(2 * density_factor))
            )
            occupied_dock_ids = (
                set(ordered_dock_ids[-occupied_count:])
                if design.presentation.entourage_density == "high" and occupied_count
                else set()
            )
            # The shared renderer deliberately parks service vehicles at a few approved docks.
            # Detail cameras must select a different bay so the door itself remains assessable.
            loading_candidates = [
                candidate
                for candidate in all_loading_candidates
                if candidate[2].dock_id not in occupied_dock_ids
            ] or all_loading_candidates
            utility_bounds = [
                element.bounding_box
                for element in scene.elements
                if element.semantic_role is SemanticRole.UTILITY_BLOCK
            ]

            def dock_clearance(
                candidate: tuple[FacadeDesign, SceneSurface | None, LoadingDock, float],
            ) -> tuple[float, float]:
                _facade, surface, dock, side = candidate
                if surface is None:
                    return (-1.0, -1.0)
                door = tuple(
                    surface.frame.origin[index]
                    + surface.frame.u_axis[index] * (dock.u * surface.width_m)
                    for index in range(3)
                )
                if not utility_bounds:
                    return (float("inf"), float("inf"))
                lateral_distance = min(32.0, max(22.0, surface.width_m * 0.18))
                # Prefer the authored loading apron between facade and support blocks. Stepping
                # farther out can put the camera behind a utility building and hide every door.
                outward_distance = min(8.0, max(5.5, cross_span * 0.08))
                camera_xy = (
                    door[0]
                    + surface.frame.u_axis[0] * lateral_distance * side
                    + surface.frame.normal[0] * outward_distance,
                    door[1]
                    + surface.frame.u_axis[1] * lateral_distance * side
                    + surface.frame.normal[1] * outward_distance,
                )
                camera_clearance = min(
                    math.hypot(
                        max(
                            bounds.minimum[0] - camera_xy[0],
                            0.0,
                            camera_xy[0] - bounds.maximum[0],
                        ),
                        max(
                            bounds.minimum[1] - camera_xy[1],
                            0.0,
                            camera_xy[1] - bounds.maximum[1],
                        ),
                    )
                    for bounds in utility_bounds
                )
                # Score the complete sightline, not only the camera point. This prevents an
                # auxiliary block from hiding the selected logistics opening in VIEW-03/06.
                line_clearance = float("inf")
                for step in range(1, 10):
                    ratio = step / 10
                    sample_x = camera_xy[0] + (door[0] - camera_xy[0]) * ratio
                    sample_y = camera_xy[1] + (door[1] - camera_xy[1]) * ratio
                    line_clearance = min(
                        line_clearance,
                        *(
                            math.hypot(
                                max(
                                    bounds.minimum[0] - sample_x,
                                    0.0,
                                    sample_x - bounds.maximum[0],
                                ),
                                max(
                                    bounds.minimum[1] - sample_y,
                                    0.0,
                                    sample_y - bounds.maximum[1],
                                ),
                            )
                            for bounds in utility_bounds
                        ),
                    )
                return (line_clearance, camera_clearance)

            if loading_candidates:
                _facade, surface, dock, side = max(loading_candidates, key=dock_clearance)
                if surface is not None:
                    frame = surface.frame
                    door = tuple(
                        frame.origin[index] + frame.u_axis[index] * (dock.u * surface.width_m)
                        for index in range(3)
                    )
                    lateral_distance = min(32.0, max(22.0, surface.width_m * 0.18))
                    outward_distance = min(8.0, max(5.5, cross_span * 0.08))
                    target = (door[0], door[1], minimum[2] + min(3.0, height * 0.28))
                    loading_detail_shot = (
                        (
                            door[0]
                            + frame.u_axis[0] * lateral_distance * side
                            + frame.normal[0] * outward_distance,
                            door[1]
                            + frame.u_axis[1] * lateral_distance * side
                            + frame.normal[1] * outward_distance,
                            # A narrow yard with auxiliary blocks needs the permitted low-drone
                            # variant so the operational facade is not hidden by foreground plant.
                            minimum[2] + min(12.0, max(8.0, height * 0.45)),
                        ),
                        target,
                    )
                    # Keep the close facade camera inside the verified service apron. A larger
                    # normal offset can cross a narrow yard and put the camera inside the
                    # opposite support building even though its target remains valid.
                    facade_detail_lateral = min(26.0, max(22.0, surface.width_m * 0.14))
                    facade_detail_outward = outward_distance
                    facade_detail_shot = (
                        (
                            door[0]
                            + frame.u_axis[0] * facade_detail_lateral * side
                            + frame.normal[0] * facade_detail_outward,
                            door[1]
                            + frame.u_axis[1] * facade_detail_lateral * side
                            + frame.normal[1] * facade_detail_outward,
                            minimum[2] + 2.8,
                        ),
                        target,
                    )
                    # Stay inside the service apron, between support blocks and the shed. Moving
                    # farther out places a human camera in perimeter planting or behind utilities.
                    human_side = -1.0 if dock.u >= 0.5 else 1.0
                    human_lateral = min(32.0, max(25.0, surface.width_m * 0.18))
                    human_outward = min(6.0, max(4.8, cross_span * 0.065))
                    human_target_shift = min(10.0, max(6.0, surface.width_m * 0.05))
                    loading_human_shot = (
                        (
                            door[0]
                            + frame.u_axis[0] * human_lateral * human_side
                            + frame.normal[0] * human_outward,
                            door[1]
                            + frame.u_axis[1] * human_lateral * human_side
                            + frame.normal[1] * human_outward,
                            minimum[2] + 1.65,
                        ),
                        (
                            door[0] - frame.u_axis[0] * human_target_shift * human_side,
                            door[1] - frame.u_axis[1] * human_target_shift * human_side,
                            minimum[2] + min(3.2, height * 0.3),
                        ),
                    )
                    building_prefix = surface.surface_id.rsplit(":", 1)[0]
                    reverse_surfaces = [
                        candidate
                        for candidate in scene.surfaces
                        if candidate.surface_id.rsplit(":", 1)[0] == building_prefix
                        and candidate.width_m >= surface.width_m * 0.80
                        and sum(
                            candidate.frame.normal[index] * frame.normal[index]
                            for index in range(3)
                        )
                        < -0.90
                    ]
                    if reverse_surfaces:
                        reverse = max(reverse_surfaces, key=lambda candidate: candidate.width_m)
                        reverse_offset = min(24.0, max(16.0, cross_span * 0.22))
                        reverse_facade_shot = (
                            (
                                reverse.frame.origin[0]
                                + reverse.frame.u_axis[0] * reverse.width_m * 0.12
                                + reverse.frame.normal[0] * reverse_offset,
                                reverse.frame.origin[1]
                                + reverse.frame.u_axis[1] * reverse.width_m * 0.12
                                + reverse.frame.normal[1] * reverse_offset,
                                minimum[2] + 2.2,
                            ),
                            (
                                reverse.frame.origin[0]
                                + reverse.frame.u_axis[0] * reverse.width_m * 0.62,
                                reverse.frame.origin[1]
                                + reverse.frame.u_axis[1] * reverse.width_m * 0.62,
                                minimum[2] + max(4.2, height * 0.26),
                            ),
                        )

        def access_facade_point(long_coordinate: float, z: float) -> tuple[float, float, float]:
            coordinate = [center[0], center[1], z]
            coordinate[long_axis] = long_coordinate
            coordinate[cross_axis] = access_facade_cross
            return tuple(coordinate)  # type: ignore[return-value]

        cameras = (
            Camera(
                view_id="view-01",
                role=ViewRole.OVERALL,
                position=overall_position,
                target=overall_target,
                focal_length_mm=28,
                sensor_width_mm=36,
                aspect_ratio="16:9",
            ),
            Camera(
                view_id="view-02",
                role=ViewRole.CONTEXT,
                position=(
                    arrival_shot[0]
                    if arrival_shot is not None
                    else point(
                        -(long_span / 2 + max(32.0, long_span * 0.16)),
                        -(cross_span / 2 + max(16.0, cross_span * 0.18)),
                        minimum[2] + 1.75,
                    )
                ),
                target=(
                    arrival_shot[1]
                    if arrival_shot is not None
                    else point(-long_span * 0.18, -cross_span * 0.30, minimum[2] + 3.0)
                ),
                focal_length_mm=32,
                sensor_width_mm=36,
                aspect_ratio="16:9",
            ),
            Camera(
                view_id="view-03",
                role=ViewRole.HERO,
                position=(
                    loading_detail_shot[0]
                    if loading_detail_shot is not None
                    else _axis_point(
                        center,
                        long_axis,
                        -(long_span / 2 + max(20.0, long_span * 0.08)),
                        (corridor_cross - center[cross_axis]) - max(18.0, cross_span * 0.20),
                        minimum[2] + 3.2,
                    )
                ),
                target=(
                    loading_detail_shot[1]
                    if loading_detail_shot is not None
                    else access_facade_point(
                        long_min + long_span * 0.38,
                        minimum[2] + height * 0.25,
                    )
                ),
                focal_length_mm=35,
                sensor_width_mm=36,
                aspect_ratio="16:9",
            ),
            Camera(
                view_id="view-04",
                role=ViewRole.DETAIL,
                position=reverse_overall_position,
                target=reverse_overall_target,
                focal_length_mm=28,
                sensor_width_mm=36,
                aspect_ratio="16:9",
            ),
            Camera(
                view_id="view-05",
                role=ViewRole.OFFICE_HERO,
                position=(
                    office_detail_shot[0]
                    if office_detail_shot is not None
                    else facade_detail_shot[0]
                    if facade_detail_shot is not None
                    else point(
                        -(long_span / 2 + max(18.0, long_span * 0.08)),
                        -(cross_span / 2 + max(14.0, cross_span * 0.14)),
                        minimum[2] + 1.85,
                    )
                ),
                target=(
                    office_detail_shot[1]
                    if office_detail_shot is not None
                    else facade_detail_shot[1]
                    if facade_detail_shot is not None
                    else access_facade_point(
                        long_min + long_span * 0.24, minimum[2] + min(3.6, height * 0.32)
                    )
                ),
                focal_length_mm=35,
                sensor_width_mm=36,
                aspect_ratio="16:9",
            ),
            Camera(
                view_id="view-06",
                role=ViewRole.LOADING_DETAIL,
                position=(
                    golden_arrival_shot[0]
                    if golden_arrival_shot is not None
                    else office_detail_shot[0]
                    if office_detail_shot is not None
                    else loading_human_shot[0]
                    if loading_human_shot is not None
                    else reverse_facade_shot[0]
                    if reverse_facade_shot is not None
                    else corridor_point(long_min + long_span * 0.10, minimum[2] + 1.65)
                ),
                target=(
                    golden_arrival_shot[1]
                    if golden_arrival_shot is not None
                    else office_detail_shot[1]
                    if office_detail_shot is not None
                    else loading_human_shot[1]
                    if loading_human_shot is not None
                    else reverse_facade_shot[1]
                    if reverse_facade_shot is not None
                    else access_facade_point(
                        long_min + long_span * 0.58,
                        minimum[2] + min(3.2, height * 0.3),
                    )
                ),
                focal_length_mm=35,
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
            view_set_id=f"{revision_key}-{design_revision}-standard-v39",
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
