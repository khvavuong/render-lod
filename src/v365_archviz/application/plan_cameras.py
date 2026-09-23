"""Deterministic standard camera planning for an industrial campus."""

from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path

from v365_archviz.application.camera_framing import (
    elevation_direction,
    focal_length_for_roofline,
    framed_distance,
    half_fov_deg,
)
from v365_archviz.artifacts import atomic_write
from v365_archviz.domain.design import (
    BuildingTreatment,
    DesignDNA,
    DesignEvidenceState,
    Entrance,
    FacadeDesign,
    LoadingDock,
)
from v365_archviz.domain.photography_pack import PhotographyPack, RoleFraming
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


DEFAULT_PHOTOGRAPHY_PACK_PATH = Path("resource/photography_packs/documentary_industrial.json")


def _default_photography_pack() -> PhotographyPack:
    """Fall back to the checked-in documentary pack when a caller supplies none."""

    return PhotographyPack.load(DEFAULT_PHOTOGRAPHY_PACK_PATH)


@dataclass(frozen=True, slots=True)
class ElevationShot:
    """Where a ground-level camera stands, and the lens it uses from there.

    The two travel together so that a frame fitted with one lens is never rendered with another;
    every earlier framing bug in this module was a version of that.
    """

    distance_m: float
    focal_length_mm: float


def _outward_clearance(
    origin: tuple[float, float, float],
    direction: tuple[float, float, float],
    blockers: list[SceneElement],
) -> float:
    """First building intersection on this camera's outward ray, not the campus corridor gap."""
    nearest = float("inf")
    for element in blockers:
        bounds = element.bounding_box
        if not bounds.minimum[2] <= origin[2] <= bounds.maximum[2]:
            continue
        entry, exit = -float("inf"), float("inf")
        for axis in (0, 1):
            if abs(direction[axis]) < 1e-8:
                if not bounds.minimum[axis] <= origin[axis] <= bounds.maximum[axis]:
                    entry, exit = 1.0, -1.0
                    break
            else:
                first = (bounds.minimum[axis] - origin[axis]) / direction[axis]
                last = (bounds.maximum[axis] - origin[axis]) / direction[axis]
                entry, exit = max(entry, min(first, last)), min(exit, max(first, last))
        if exit >= max(entry, 0.0):
            nearest = min(nearest, max(0.0, entry) - 1.0)
    return max(2.0, nearest)


def _elevation_stand_off(
    subject_height_m: float,
    framing: RoleFraming,
    available_clearance_m: float,
) -> ElevationShot:
    """Stand-off for a ground-level camera looking at one elevation.

    A detail elevation is framed on the building height: stand back far enough to hold the wall
    from plinth to parapet, and the width follows. The subject is therefore treated as roughly
    as wide as the building is tall — neither the opening alone, which is a few metres, nor the
    whole elevation, which can be hundreds. Solving it this way keeps the same intent on an 11 m
    shed and a 15 m unit, where a tuned metre value put the camera against the cladding.
    """

    eye_height = framing.eye_height_m or 1.7
    wanted = framed_distance(
        ((0.0, 0.0, 0.0), (subject_height_m, subject_height_m, subject_height_m)),
        camera_height_m=eye_height,
        tilt_deg=framing.elevation_deg,
        focal_length_mm=framing.focal_length_mm,
        target_width_coverage=framing.target_width_coverage,
        roofline_margin=framing.roofline_margin,
    )
    # The site may not have room for the framing the pack asks for. A yard only so deep cannot
    # be backed out of, and a stand-off that ignores it puts the camera inside the shed on the
    # far side, which renders as a blank wall. Clamping keeps the camera on the apron; the
    # conditioning gate then reports the framing it could not reach.
    #
    # When the clamp binds, the pack's lens no longer holds the roofline from where the camera
    # can stand, and the frame the provider receives has its parapet cut off. `framed_focal_length`
    # and `tilt_for_roofline` solve that exactly, but widening to hold an 11 m roofline from 23.6 m
    # needs 18 mm, and at 18 mm the subject falls to 8% of the frame: measured on this model the
    # conditioning gate then rejects the view for `focus_subject_too_small_or_missing`, where the
    # unwidened frame passed at 21%. Holding the roofline and holding the subject share are not
    # both reachable from that distance, so widening here only moves the failure from the provider
    # to the gate. The distance is what is wrong — `_corridor_gap_m` hands an office-entrance shot
    # the clearance between two sheds, when that camera stands in the arrival yard — and until the
    # clearance model is right, guessing a lens on top of a wrong distance is not an improvement.
    return ElevationShot(min(wanted, max(2.0, available_clearance_m)), framing.focal_length_mm)


def _anchor_to_facade_end(
    feature: tuple[float, float],
    frame_origin: tuple[float, float, float],
    u_axis: tuple[float, float, float],
    facade_width_m: float,
    stand_off_m: float,
    focal_length_mm: float,
) -> tuple[float, float]:
    """Slide a target along its facade so the building's end stays inside the frame.

    A dock or entrance in the middle of a long run gives a camera nothing to compose against: the
    facade leaves both sides of the frame and the photograph is cladding. Measured on the 352 m
    reference shed, every ground-level view aimed at a mid-facade feature came back as a wall.

    Moving the aim point towards the nearer end brings the corner into the field of view, so the
    building turns and reads as a volume. The shift is only as large as the frame requires: on a
    facade already shorter than the view covers, the feature keeps its own position.
    """

    half_width_m = math.tan(math.radians(half_fov_deg(focal_length_mm)[0])) * stand_off_m
    origin_to_feature = (feature[0] - frame_origin[0], feature[1] - frame_origin[1])
    along = origin_to_feature[0] * u_axis[0] + origin_to_feature[1] * u_axis[1]
    near_end = 0.0 if along <= facade_width_m / 2 else facade_width_m
    # Keep the end within one frame half-width of the aim point, and never move past the end.
    limit = half_width_m * 0.8
    if abs(along - near_end) <= limit:
        return feature
    shifted = near_end + limit if near_end == 0.0 else near_end - limit
    delta = shifted - along
    # Never move so far that the feature this view exists to show leaves the frame. Measured on
    # the compact reference model, an unbounded shift dropped the office entrance out of view and
    # the conditioning gate reported the subject at 3% of frame: an end-on corner with nothing in
    # it is no better than the wall this anchoring was added to avoid.
    reach = half_width_m * 0.6
    if abs(delta) > reach:
        delta = math.copysign(reach, delta)
    return feature[0] + u_axis[0] * delta, feature[1] + u_axis[1] * delta


def _axis_bearing(long_axis: int, long_offset: float, cross_offset: float) -> tuple[float, float]:
    """Map a project-relative horizontal bearing to world XY."""

    if long_axis == 0:
        return long_offset, cross_offset
    return cross_offset, long_offset


#: How much each kind of site evidence says "the building is approached from this side".
#: An authored entrance is the strongest statement a model can make about its own front; roads
#: and yards say where people and trucks actually arrive; an office block says where the address
#: is. Nothing here is tuned to a project — these are the roles the canonicaliser emits, weighted
#: by how directly each one answers the question.
_ACCESS_EVIDENCE_WEIGHTS = {
    SemanticRole.MAIN_ENTRANCE: 3.0,
    SemanticRole.OFFICE_BLOCK: 2.0,
    SemanticRole.PARKING: 1.5,
    SemanticRole.LOADING_ZONE: 1.2,
    SemanticRole.SITE_ROAD: 1.0,
    SemanticRole.SIDEWALK: 0.8,
}


def _access_bearing(
    scene: CanonicalScene,
    long_axis: int,
    site_centre: tuple[float, float],
) -> tuple[float, float] | None:
    """Project-relative direction of the site's own access evidence, or None when it has none.

    The aerial bearings used to be two fixed quadrants relative to the building's long axis. That
    rotates with the building but never changes which corner it chooses, so on a site whose
    approach road, gatehouse and office all sit on one side, the overview could be orbited to the
    blank rear yard and still be "correct" by the rule. Deriving the bearing from what the model
    actually contains costs nothing — it is a weighted centroid of element positions — and is the
    difference between a planner that adapts to a site and one that adapts only to its dimensions.

    Returns a unit-ish (long, cross) offset suitable for `_axis_bearing`, or None when the scene
    carries no access evidence at all and the caller must fall back to a geometric default.
    """

    cross_axis = 1 - long_axis
    weight_total = 0.0
    long_offset = 0.0
    cross_offset = 0.0
    for element in scene.elements:
        weight = _ACCESS_EVIDENCE_WEIGHTS.get(element.semantic_role)
        if weight is None:
            continue
        bounds = element.bounding_box
        centre = (
            (bounds.minimum[long_axis] + bounds.maximum[long_axis]) / 2,
            (bounds.minimum[cross_axis] + bounds.maximum[cross_axis]) / 2,
        )
        # Footprint area scales the vote: one large apron says more about where the front is
        # than a dozen kerb segments.
        area = max(
            1.0,
            (bounds.maximum[long_axis] - bounds.minimum[long_axis])
            * (bounds.maximum[cross_axis] - bounds.minimum[cross_axis]),
        )
        vote = weight * math.sqrt(area)
        long_offset += vote * (centre[0] - site_centre[0])
        cross_offset += vote * (centre[1] - site_centre[1])
        weight_total += vote
    if weight_total <= 0.0:
        return None
    long_offset /= weight_total
    cross_offset /= weight_total
    magnitude = math.hypot(long_offset, cross_offset)
    if magnitude <= 1e-6:
        return None
    return long_offset / magnitude, cross_offset / magnitude


def _complementary_bearing(bearing: tuple[float, float]) -> tuple[float, float]:
    """The opposite corner, so the second aerial shows what the first one could not."""

    return -bearing[0], -bearing[1]


def _aerial_camera(
    bounds: tuple[tuple[float, float, float], tuple[float, float, float]],
    target: tuple[float, float, float],
    horizontal_bearing: tuple[float, float],
    framing: RoleFraming,
) -> tuple[float, float, float]:
    """Place an aerial camera from photographic intent rather than a tuned stand-off.

    Elevation, lens and subject share come from the photography pack; the distance that delivers
    them is solved from this model's own bounds, so the same intent holds whatever the site
    measures.
    """

    direction = elevation_direction(horizontal_bearing, framing.elevation_deg)
    minimum, maximum = bounds
    apex = maximum[2] - target[2]
    distance = framed_distance(
        ((minimum[0], minimum[1], 0.0), (maximum[0], maximum[1], apex)),
        camera_height_m=0.0,
        tilt_deg=framing.elevation_deg,
        focal_length_mm=framing.focal_length_mm,
        target_width_coverage=framing.target_width_coverage,
        roofline_margin=framing.roofline_margin,
    )
    return (
        target[0] + direction[0] * distance,
        target[1] + direction[1] * distance,
        target[2] + direction[2] * distance,
    )


def _corridor_gap_m(design: DesignDNA | None, long_axis: int) -> float | None:
    """Width of the widest gap between parallel roof assemblies, in metres."""

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
    gaps = [
        upper.bounding_box.minimum[cross_axis] - lower.bounding_box.maximum[cross_axis]
        for lower, upper in pairwise(ordered)
    ]
    positive = [gap for gap in gaps if gap > 0]
    return max(positive) if positive else None


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


#: Roles a camera cannot stand inside. Ground and site surfaces are excluded on
#: purpose: a camera standing on the apron is inside the apron slab's box, and
#: that is where it belongs.
SOLID_ROLES = frozenset(
    {
        SemanticRole.MAIN_SHED,
        SemanticRole.OFFICE_BLOCK,
        SemanticRole.UTILITY_BLOCK,
        SemanticRole.ENVELOPE_PANEL,
    }
)

#: How many boxes a standpoint may be pushed out of before the search gives up.
#: Leaving one building can put the camera inside the next, so the eviction is
#: iterative; three buildings deep is already further than any authored site.
MAXIMUM_EVICTIONS = 8


def _solid_footprints(
    scene: CanonicalScene,
) -> tuple[tuple[float, float, float, float, float, float], ...]:
    """The boxes a camera must stay out of, as (x0, y0, z0, x1, y1, z1)."""

    return tuple(
        (
            element.bounding_box.minimum[0],
            element.bounding_box.minimum[1],
            element.bounding_box.minimum[2],
            element.bounding_box.maximum[0],
            element.bounding_box.maximum[1],
            element.bounding_box.maximum[2],
        )
        for element in scene.elements
        if element.semantic_role in SOLID_ROLES
    )


#: How far off a facade plane an authored opening may sit and still belong to it.
#: A dock door is modelled in the wall, so its centre is within the wall's own
#: thickness of the plane; a metre of tolerance covers a reveal or a sill.
FACADE_ATTACHMENT_TOLERANCE_M = 1.5


#: Where an elevation is probed for somewhere to stand. A LOD200 office is
#: usually built against the shed it serves, so one or two of its four box
#: faces are buried in the neighbour; aiming at a buried face puts the camera
#: inside that neighbour, and once evicted it looks at the neighbour's back.
APPROACH_PROBES_M = (6.0, 14.0)


def _facades_of(
    scene: CanonicalScene,
    roles: frozenset[SemanticRole],
    solids: tuple[tuple[float, float, float, float, float, float], ...] = (),
) -> list[SceneSurface]:
    """The vertical surfaces of the masses a camera can be aimed at.

    With `solids`, only the ones a camera can stand in front of.
    """

    subjects = {
        element.scene_element_id
        for element in scene.elements
        if element.semantic_role in roles
    }
    facades = [
        surface
        for surface in scene.surfaces
        if surface.element_id in subjects and abs(surface.frame.normal[2]) < 0.1
    ]
    if not solids:
        return facades
    approachable = [
        surface for surface in facades if _is_approachable(surface, solids)
    ]
    # An elevation with nowhere to stand is still better than no elevation at
    # all: a courtyard model where every face is enclosed should fall through
    # to the gate's own report rather than to a silent empty list.
    return approachable or facades


def _is_approachable(
    surface: SceneSurface,
    solids: tuple[tuple[float, float, float, float, float, float], ...],
) -> bool:
    """Whether there is open air in front of this elevation to photograph it from."""

    frame = surface.frame
    middle = (
        frame.origin[0] + frame.u_axis[0] * surface.width_m / 2,
        frame.origin[1] + frame.u_axis[1] * surface.width_m / 2,
        frame.origin[2] + surface.height_m / 2,
    )
    return all(
        _escape_once(
            middle[0] + frame.normal[0] * probe,
            middle[1] + frame.normal[1] * probe,
            middle[2],
            solids,
            0.0,
        )
        is None
        for probe in APPROACH_PROBES_M
    )


def _position_on_facade(surface: SceneSurface, point: tuple[float, float]) -> float | None:
    """Where along a facade a point sits, as a fraction of its width, or None.

    None when the point is off the end of the facade or too far off its plane to
    have been modelled in it.
    """

    frame = surface.frame
    offset = (point[0] - frame.origin[0], point[1] - frame.origin[1])
    along = offset[0] * frame.u_axis[0] + offset[1] * frame.u_axis[1]
    away = abs(offset[0] * frame.normal[0] + offset[1] * frame.normal[1])
    if away > FACADE_ATTACHMENT_TOLERANCE_M:
        return None
    if not 0.0 <= along <= surface.width_m:
        return None
    return along / surface.width_m


def _authored_dock_candidates(
    scene: CanonicalScene,
) -> list[tuple[FacadeDesign | None, SceneSurface | None, LoadingDock, float]]:
    """The dock doors the model itself draws, as the shot builder expects them.

    The design plan invents docks only when the brief asks it to, and a LOD200
    brief asks it not to: the doors are already drawn, so `logistics kit =
    preserve_model`. The planner then had nothing to aim the two logistics views
    at and fell back to arithmetic on the site bounding box — on a 176 m site
    that stands the camera 180 m from its subject with a 35 mm lens. The doors
    were there the whole time; nothing was reading them.
    """

    solids = _solid_footprints(scene)
    facades = _facades_of(
        scene, frozenset({SemanticRole.MAIN_SHED, SemanticRole.OFFICE_BLOCK}), solids
    )
    if not facades:
        return []
    docks = [
        element for element in scene.elements if element.semantic_role is SemanticRole.LOADING_DOCK
    ]
    on_facade: dict[str, list[tuple[SceneSurface, LoadingDock]]] = {}
    for index, dock in enumerate(docks, start=1):
        box = dock.bounding_box
        centre = (
            (box.minimum[0] + box.maximum[0]) / 2,
            (box.minimum[1] + box.maximum[1]) / 2,
        )
        placements = [
            (surface, position)
            for surface in facades
            if (position := _position_on_facade(surface, centre)) is not None
        ]
        if not placements:
            continue
        # A door sits in one wall. When two walls claim it — a shed's own panel
        # and the derived mass it belongs to — the widest is the elevation a
        # photographer would stand in front of.
        surface, position = max(placements, key=lambda placement: placement[0].width_m)
        authored = LoadingDock(
            dock_id=f"authored-dock-{index:02d}",
            u=min(1.0, max(0.0, position)),
            width_m=max(0.8, box.maximum[0] - box.minimum[0], box.maximum[1] - box.minimum[1]),
            clear_height_m=min(6.5, max(3.2, box.maximum[2] - box.minimum[2])),
            evidence_state=DesignEvidenceState.AUTHORED,
        )
        on_facade.setdefault(surface.surface_id, []).append((surface, authored))
    if not on_facade:
        return []
    # One elevation, not eighteen scattered doors. The wall the model puts most
    # of its doors in is the operational face, and a logistics view is of that
    # face; picking a door off a wall that has one puts the camera at the quiet
    # end of the building with nothing around it to photograph.
    chosen = max(
        on_facade.values(),
        key=lambda placements: (len(placements), placements[0][0].width_m),
    )
    return [
        (None, surface, dock, side)
        for surface, dock in chosen
        for side in (-1.0, 1.0)
    ]


def _authored_office_candidates(
    scene: CanonicalScene,
) -> list[tuple[FacadeDesign | None, SceneSurface | None, Entrance | None]]:
    """The office block's own elevation, when the brief invents no entrance.

    `add_office_entrances` is false whenever the entrance kit preserves the
    model, which is the honest setting for a model that drew its own. Without
    this the office view had nothing authored to stand in front of either.
    """

    facades = _facades_of(
        scene, frozenset({SemanticRole.OFFICE_BLOCK}), _solid_footprints(scene)
    )
    if not facades:
        return []
    # Centre of the widest elevation: with no authored door position to use,
    # the middle of the longest wall is the least arbitrary place to aim.
    surface = max(facades, key=lambda candidate: candidate.width_m)
    entrance = Entrance(
        u=0.5,
        width_m=min(2.4, surface.width_m * 0.25),
        evidence_state=DesignEvidenceState.INFERRED_PROPOSAL,
    )
    return [(None, surface, entrance)]


#: The furthest off a facade's normal a ground-level camera is allowed to stand,
#: as a fraction of its stand-off. A door four metres wide seen from sixty
#: degrees off is two metres of pixels behind its own reveal, and the
#: conditioning gate then reports — correctly — that the subject of the view is
#: not visible. Thirty-five degrees still reads as a three-quarter view and
#: still shows the depth of the yard.
MAXIMUM_OBLIQUITY = math.tan(math.radians(35.0))


def _legible_lateral(lateral: float, outward: float) -> float:
    """Pull a sideways offset back until the elevation is still worth photographing."""

    return min(lateral, outward * MAXIMUM_OBLIQUITY)


#: The margin kept when the requested clearance will not fit. A yard narrower
#: than twice the clearance makes the full stand-off impossible, and a camera
#: bouncing between two walls ends inside one of them. The guarantee is that the
#: lens is in open air; the clearance is what the planner asks for on top.
MINIMUM_CLEARANCE_M = 1.0


def _escape_once(
    x: float,
    y: float,
    z: float,
    solids: tuple[tuple[float, float, float, float, float, float], ...],
    clearance: float,
) -> tuple[float, float] | None:
    """The shortest move that leaves the box the point is deepest inside, or None.

    Containment is strict: a camera standing in front of a wall is where the
    shot solvers put it, and a close elevation is a photograph, not a fault.
    Only a lens inside the building is wrong, and `clearance` is how far out
    such a camera is placed once it has been found — not a stand-off imposed on
    cameras that were already in open air.
    """

    escapes: list[tuple[float, float, float]] = []
    for x0, y0, z0, x1, y1, z1 in solids:
        if not (z0 <= z <= z1 and x0 <= x <= x1 and y0 <= y <= y1):
            continue
        # Four ways out; take the shortest, so the camera keeps as much of the
        # framing the planner asked for as it can.
        candidates = (
            (x0 - clearance - x, 0.0),
            (x1 + clearance - x, 0.0),
            (0.0, y0 - clearance - y),
            (0.0, y1 + clearance - y),
        )
        shift = min(candidates, key=lambda offset: math.hypot(*offset))
        escapes.append((math.hypot(*shift), shift[0], shift[1]))
    if not escapes:
        return None
    # Resolve the deepest intrusion first: a shallow one may disappear on its
    # own once the camera has left the building it is actually inside.
    _, shift_x, shift_y = max(escapes)
    return shift_x, shift_y


def _evict(
    position: tuple[float, float, float],
    solids: tuple[tuple[float, float, float, float, float, float], ...],
    clearance: float,
) -> tuple[float, float, float]:
    x, y, z = position
    for _ in range(MAXIMUM_EVICTIONS):
        shift = _escape_once(x, y, z, solids, clearance)
        if shift is None:
            break
        x += shift[0]
        y += shift[1]
    return (x, y, z)


def _free_standpoint(
    position: tuple[float, float, float],
    solids: tuple[tuple[float, float, float, float, float, float], ...],
    clearance: float,
) -> tuple[float, float, float]:
    """Move a camera out of any building it stands inside, through the nearest wall.

    The planner places ground-level cameras by arithmetic on a bounding box —
    "back off the facade by a quarter of the cross span", "stand a tenth of the
    way along". On a single shed in an open site every such offset lands in open
    air, which is why the arithmetic survived this long. On a site with two rows
    of sheds it lands inside one of them, and a camera inside a wall renders a
    frame that is one hundred percent cladding: the conditioning gate reports it
    as an excessively cropped subject, which is true but says nothing about the
    real fault.

    No offset can be trusted to be in open air, so the standpoint is checked
    against the geometry instead of argued about. Height is left alone: a camera
    at eye level is inside a building's box vertically by definition, and lifting
    it out would put the lens on the roof.
    """

    if not solids:
        return position
    placed = _evict(position, solids, clearance)
    if _escape_once(*placed, solids, 0.0) is None:
        return placed
    # The clearance did not fit — a yard too narrow for it bounces the camera
    # from one wall into the other. Keep the guarantee, drop the preference.
    return _evict(position, solids, MINIMUM_CLEARANCE_M)


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
    # Stand back far enough to hold the gate and its approach, but no further: a setback driven
    # by the whole site span puts the camera so far outside a large site that the building it is
    # meant to introduce shrinks below the conditioning gate's minimum subject coverage.
    setback = min(max(28.0, focus_height * 3.2), max(34.0, site_span * 0.14))
    tangent = (-outward[1], outward[0])
    lateral_offset = min(24.0, max(14.0, site_span * 0.07))
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
    def execute(
        self,
        scene_path: Path,
        design_dna_path: Path | None = None,
        photography_pack_path: Path | None = None,
        bearing_offset_deg: float = 0.0,
        *,
        output_path: Path | None = None,
    ) -> ViewSet:
        """Plan the standard set, optionally orbited off the site's own access bearing.

        `bearing_offset_deg` exists for repair rather than for taste. The conditioning gate scores
        the cameras against a real render, and when a slot fails there is no point re-rendering
        the same camera: the planner is asked for the same intent from a different side, and only
        the failed views are rendered again. Zero reproduces the plan a fresh import gets, so the
        default path stays deterministic.
        """

        photography = (
            PhotographyPack.load(photography_pack_path)
            if photography_pack_path is not None
            else _default_photography_pack()
        )
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
        # How far a ground-level camera can back away from a facade before it leaves the apron
        # and enters whatever stands opposite. Derived from the model's own yard, so a narrow
        # site clamps harder than an open one.
        corridor_gap = _corridor_gap_m(design, long_axis)
        available_apron_clearance = (
            # Stay on this side of the yard: half the gap, less the camera's own footprint.
            max(6.0, corridor_gap / 2 - 2.0)
            if corridor_gap is not None
            else max(6.0, cross_span * 0.28)
        )
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
        # Stand on the side the site says it is approached from, so the overview shows the
        # address, the gate and the yard rather than whichever corner a constant happened to
        # name. Falls back to the previous fixed quadrant only when the scene carries no access
        # evidence at all, which the conditioning gate then reports as usual.
        access_bearing = _access_bearing(
            scene, long_axis, (site_center[long_axis], site_center[1 - long_axis])
        )
        if access_bearing is not None and bearing_offset_deg:
            angle = math.radians(bearing_offset_deg)
            access_bearing = (
                access_bearing[0] * math.cos(angle) - access_bearing[1] * math.sin(angle),
                access_bearing[0] * math.sin(angle) + access_bearing[1] * math.cos(angle),
            )
        primary_bearing = (
            _axis_bearing(long_axis, access_bearing[0], access_bearing[1])
            if access_bearing is not None
            else _axis_bearing(long_axis, -1.0, -0.85)
        )
        overall_position = _aerial_camera(
            (site_minimum, site_maximum),
            overall_target,
            primary_bearing,
            photography.framing_for(ViewRole.OVERALL),
        )
        reverse_overall_target = (site_center[0], site_center[1], minimum[2] + height * 0.18)
        reverse_bearing = (
            _axis_bearing(long_axis, *_complementary_bearing(access_bearing))
            if access_bearing is not None
            else _axis_bearing(long_axis, 1.0, 0.74)
        )
        reverse_overall_position = _aerial_camera(
            (site_minimum, site_maximum),
            reverse_overall_target,
            reverse_bearing,
            photography.framing_for(ViewRole.DETAIL),
        )
        # An eye-level approach must stand close enough that the building it introduces still
        # reads. Used only by the fallback below, which runs when no gate is authored.
        site_span_for_approach = max(
            site_maximum[0] - site_minimum[0], site_maximum[1] - site_minimum[1]
        )
        # Two failure modes bracket this distance. Too far and an eye-level camera leaves the
        # lower half of the frame as featureless apron; too close and the long facade fills the
        # frame as a flat wall with no gate, depth or approach. Both are framing statements, so
        # the pack states the intent and the stand-off is solved from this model's own height.
        approach_shot = _elevation_stand_off(
            height,
            photography.framing_for(ViewRole.CONTEXT),
            # The approach stands outside the fence, so the yard does not constrain it; the site
            # itself is the only limit worth keeping.
            max(12.0, site_span_for_approach * 0.5),
        )
        approach_distance = approach_shot.distance_m
        # Place the approach camera relative to what it looks at, so approach_distance really is
        # the stand-off from the subject. Adding it to half the site length instead pushes the
        # camera past the far end of a long building and shrinks the subject out of range.
        # Aim at the outer corner of the mass, not a point inside it. Measured on the 352 m
        # reference shed, the 0.86 factor put the target 25 m inside the footprint: the camera
        # was then only 9 m off the facade plane even though the solver had asked for a 35 m
        # stand-off, and at 9 m with a 32 mm lens the wall is the entire frame. The rendered
        # approach was a blank elevation receding to a vanishing point, and the conditioning gate
        # passed it because that wall is the focus building and fills 40% of the frame.
        approach_target_long = -(long_span / 2)
        approach_target_cross = -(cross_span / 2)
        arrival_shot = _arrival_shot(
            scene,
            minimum,
            maximum,
            site_center,
            site_span_for_approach,
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
        # The lens each ground-level role ends up with. It is the pack's focal length unless the
        # site clamped the stand-off, in which case the solver widened it to hold the framing
        # from where the camera can actually stand.
        office_focal_mm = photography.framing_for(ViewRole.OFFICE_HERO).focal_length_mm
        logistics_focal_mm = photography.framing_for(ViewRole.HERO).focal_length_mm
        human_focal_mm = photography.framing_for(ViewRole.LOADING_DETAIL).focal_length_mm
        if design is not None:
            surfaces_by_id = {surface.surface_id: surface for surface in scene.surfaces}
            office_candidates: list[
                tuple[FacadeDesign | None, SceneSurface | None, Entrance | None]
            ] = [
                (facade, surfaces_by_id.get(facade.surface_id), facade.office_entrance)
                for building in design.buildings
                if building.treatment is BuildingTreatment.FOCUS
                for facade in building.facades
                if facade.office_entrance is not None
            ] or _authored_office_candidates(scene)
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
                    # Stand back far enough that the whole elevation, parapet included, fits the
                    # frame. Measured on the reference model the roofline sat about half a degree
                    # outside the field of view, and a clipped parapet is not a frame a
                    # photographer would keep, so the provider pulls the camera back itself and
                    # the geometry screen then reports that as drift.
                    office_shot = _elevation_stand_off(
                        height,
                        photography.framing_for(ViewRole.OFFICE_HERO),
                        float("inf"),
                    )
                    outward = office_shot.distance_m
                    office_focal_mm = office_shot.focal_length_mm
                    anchored_entrance = _anchor_to_facade_end(
                        (entrance[0], entrance[1]),
                        frame.origin,
                        frame.u_axis,
                        office_surface.width_m,
                        outward,
                        office_focal_mm,
                    )
                    own_assembly = next(
                        (
                            assembly
                            for assembly in design.roof_assemblies
                            if office_surface.element_id in assembly.building_ids
                        ),
                        None,
                    )
                    excluded = (
                        set(own_assembly.building_ids)
                        if own_assembly
                        else {office_surface.element_id}
                    )
                    ray_origin = (
                        anchored_entrance[0] + frame.u_axis[0] * lateral * side,
                        anchored_entrance[1] + frame.u_axis[1] * lateral * side,
                        minimum[2] + 1.85,
                    )
                    blockers = [
                        element
                        for element in scene.elements
                        if element.scene_element_id not in excluded
                        and element.semantic_role
                        in {SemanticRole.MAIN_SHED, SemanticRole.OFFICE_BLOCK}
                    ]
                    outward = min(outward, _outward_clearance(ray_origin, frame.normal, blockers))
                    office_framing = photography.framing_for(ViewRole.OFFICE_HERO)
                    office_focal_mm = min(
                        office_focal_mm,
                        max(
                            18.0,
                            focal_length_for_roofline(
                                height,
                                1.85,
                                office_framing.elevation_deg,
                                math.hypot(outward, lateral),
                                margin=office_framing.roofline_margin,
                            ),
                        ),
                    )
                    office_detail_shot = (
                        (
                            anchored_entrance[0]
                            + frame.u_axis[0] * lateral * side
                            + frame.normal[0] * outward,
                            anchored_entrance[1]
                            + frame.u_axis[1] * lateral * side
                            + frame.normal[1] * outward,
                            minimum[2] + 1.85,
                        ),
                        (
                            anchored_entrance[0],
                            anchored_entrance[1],
                            minimum[2]
                            + 1.85
                            + math.hypot(outward, lateral)
                            * math.tan(math.radians(office_framing.elevation_deg)),
                        ),
                    )
            all_loading_candidates: list[
                tuple[FacadeDesign | None, SceneSurface | None, LoadingDock, float]
            ] = [
                (facade, surfaces_by_id.get(facade.surface_id), dock, side)
                for building in design.buildings
                if building.treatment is BuildingTreatment.FOCUS
                for facade in building.facades
                for dock in facade.loading_docks
                for side in (-1.0, 1.0)
            ] or _authored_dock_candidates(scene)
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
                candidate: tuple[FacadeDesign | None, SceneSurface | None, LoadingDock, float],
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
                    # The logistics view has to prove the yard works, so it must stand back far
                    # enough to show the apron and turning space in front of the dock. Standing
                    # closer than the building is tall fills the frame with cladding and the
                    # conditioning gate rejects it for hiding the authored circulation.
                    logistics_shot = _elevation_stand_off(
                        height,
                        photography.framing_for(ViewRole.HERO),
                        available_apron_clearance,
                    )
                    logistics_outward_distance = logistics_shot.distance_m
                    logistics_focal_mm = logistics_shot.focal_length_mm
                    anchored_door = _anchor_to_facade_end(
                        (door[0], door[1]),
                        surface.frame.origin,
                        surface.frame.u_axis,
                        surface.width_m,
                        logistics_outward_distance,
                        logistics_focal_mm,
                    )
                    legible_lateral = _legible_lateral(
                        lateral_distance, logistics_outward_distance
                    )
                    target = (
                        anchored_door[0],
                        anchored_door[1],
                        minimum[2] + min(3.0, height * 0.28),
                    )
                    loading_detail_shot = (
                        (
                            anchored_door[0]
                            + frame.u_axis[0] * legible_lateral * side
                            + frame.normal[0] * logistics_outward_distance,
                            anchored_door[1]
                            + frame.u_axis[1] * legible_lateral * side
                            + frame.normal[1] * logistics_outward_distance,
                            # A narrow yard with auxiliary blocks needs the permitted low-drone
                            # variant so the operational facade is not hidden by foreground plant.
                            minimum[2] + min(12.0, max(8.0, height * 0.45)),
                        ),
                        target,
                    )
                    # Keep the close facade camera inside the verified service apron. A larger
                    # normal offset can cross a narrow yard and put the camera inside the
                    # opposite support building even though its target remains valid.
                    facade_detail_outward = outward_distance
                    facade_detail_lateral = _legible_lateral(
                        min(26.0, max(22.0, surface.width_m * 0.14)), facade_detail_outward
                    )
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
                    human_shot = _elevation_stand_off(
                        height,
                        photography.framing_for(ViewRole.LOADING_DETAIL),
                        available_apron_clearance,
                    )
                    human_outward = human_shot.distance_m
                    human_focal_mm = human_shot.focal_length_mm
                    human_lateral = _legible_lateral(human_lateral, human_outward)
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
                focal_length_mm=photography.framing_for(ViewRole.OVERALL).focal_length_mm,
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
                        # Stand on the outward diagonal from that corner so both facades meeting
                        # there stay in frame. A displacement weighted towards the long axis
                        # points the camera down the length of the building instead of across
                        # its corner, which is what makes a long shed photograph as a wall.
                        approach_target_long - approach_distance * 0.60,
                        approach_target_cross - approach_distance * 0.80,
                        minimum[2] + 1.75,
                    )
                ),
                target=(
                    arrival_shot[1]
                    if arrival_shot is not None
                    # Aim at the near corner of the authored mass, not deep into the site: a
                    # distant target drags the whole composition away from the building this
                    # view exists to introduce.
                    else point(
                        approach_target_long,
                        approach_target_cross,
                        # Aim at mid-height so the camera tilts up off the apron rather than
                        # holding the horizon across the middle of the frame.
                        minimum[2] + max(4.0, height * 0.55),
                    )
                ),
                focal_length_mm=approach_shot.focal_length_mm,
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
                focal_length_mm=logistics_focal_mm,
                sensor_width_mm=36,
                aspect_ratio="16:9",
            ),
            Camera(
                view_id="view-04",
                role=ViewRole.DETAIL,
                position=reverse_overall_position,
                target=reverse_overall_target,
                focal_length_mm=photography.framing_for(ViewRole.DETAIL).focal_length_mm,
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
                focal_length_mm=office_focal_mm,
                sensor_width_mm=36,
                aspect_ratio="16:9",
            ),
            Camera(
                view_id="view-06",
                role=ViewRole.LOADING_DETAIL,
                # VIEW-05 already owns office_detail_shot. Falling back to it here collapses two
                # of the six deliverable angles onto one identical camera whenever the model has
                # no authored gate, which is what makes golden_arrival_shot unavailable.
                position=(
                    golden_arrival_shot[0]
                    if golden_arrival_shot is not None
                    else loading_human_shot[0]
                    if loading_human_shot is not None
                    else reverse_facade_shot[0]
                    if reverse_facade_shot is not None
                    else corridor_point(long_min + long_span * 0.10, minimum[2] + 1.65)
                ),
                target=(
                    golden_arrival_shot[1]
                    if golden_arrival_shot is not None
                    else loading_human_shot[1]
                    if loading_human_shot is not None
                    else reverse_facade_shot[1]
                    if reverse_facade_shot is not None
                    else access_facade_point(
                        long_min + long_span * 0.58,
                        minimum[2] + min(3.2, height * 0.3),
                    )
                ),
                focal_length_mm=human_focal_mm,
                sensor_width_mm=36,
                aspect_ratio="16:9",
            ),
        )
        # Nothing above this line knows whether the point it computed is in open
        # air. This does, and it is the only guarantee in the planner that does
        # not depend on the shape of the model it was tuned against.
        solids = _solid_footprints(scene)
        standpoint_clearance = max(6.0, height * 0.8)
        cameras = tuple(
            camera.model_copy(
                update={
                    "position": _free_standpoint(
                        camera.position, solids, standpoint_clearance
                    )
                }
            )
            for camera in cameras
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
            view_set_id=f"{revision_key}-{design_revision}-standard-v40",
            design_revision=design_revision,
            cameras=cameras,
        )
        output = output_path or (
            design_dna_path.parent / "view_set.json"
            if design_dna_path is not None
            else scene_path.parent / "view_set.json"
        )
        atomic_write(output, view_set.model_dump_json(indent=2).encode() + b"\n")
        return view_set
