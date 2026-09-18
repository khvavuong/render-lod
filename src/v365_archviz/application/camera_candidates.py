"""Generate and rank camera candidates instead of deciding the angles in advance.

The standard planner answers "where does the overview camera go" with a rule. That rule was tuned
against one model, and a 352 m shed row and a 150 m compact unit do not share a good angle, so the
rule is wrong for one of them whatever it says. This module replaces the decision with a search:
propose many physically valid cameras, render each one cheaply, measure what it actually shows,
and pick the set.

Everything here is measurement, not taste. The ranking reads areas out of the semantic pass —
how much of the frame the project fills, how much is empty apron, how many surface roles are
legible, whether the subject reads as a three-quarter view or a flat elevation. Those are the
quantities the conditioning gate already trusts; this module just uses them to choose rather than
only to reject.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from v365_archviz.application.camera_framing import framed_distance
from v365_archviz.domain.photography_pack import RoleFraming
from v365_archviz.domain.workflow import ViewRole

Vector3 = tuple[float, float, float]
Bounds = tuple[Vector3, Vector3]


@dataclass(frozen=True, slots=True)
class CameraCandidate:
    """One proposed camera, before anything has been rendered through it."""

    candidate_id: str
    role: ViewRole
    position: Vector3
    target: Vector3
    focal_length_mm: float
    #: Compass bearing of the camera from its target, in degrees, for diversity comparison.
    bearing_deg: float
    elevation_deg: float
    distance_m: float


@dataclass(frozen=True, slots=True)
class CandidateScore:
    """What a rendered candidate turned out to show."""

    candidate_id: str
    #: Share of frame occupied by the project's own buildings.
    subject_share: float
    #: Share of frame occupied by paving, apron and roads.
    ground_share: float
    #: Distinct semantic roles legible at more than a trivial area.
    legible_roles: int
    #: 0 when one facade plane dominates, 1 when two read equally. A flat elevation is a record
    #: shot; a three-quarter view is a photograph.
    corner_balance: float
    #: Share of the subject hidden behind entourage or context volumes.
    occlusion: float
    #: Roles that make this camera worth its slot, e.g. the entrance for an office hero.
    role_targets_visible: float
    feasible: bool = True
    notes: str = ""


@dataclass(frozen=True, slots=True)
class RoleObjective:
    """What a good photograph means for one role, as measurable bands.

    Stated as preferred ranges rather than single values: a 350 m shed and a 40 m unit cannot
    both put the same fraction of the frame on the subject and still look composed. A score of 1
    means the quantity sits inside the band; outside it falls off smoothly rather than failing,
    because a candidate that misses one band can still be the best available on a tight site.
    """

    subject_share: tuple[float, float]
    ground_share: tuple[float, float]
    minimum_legible_roles: int = 2
    prefers_corner: bool = True
    requires_role_target: bool = False
    weights: dict[str, float] = field(
        default_factory=lambda: {
            "subject": 1.0,
            "ground": 0.6,
            "roles": 0.5,
            "corner": 0.8,
            "occlusion": 1.0,
            "target": 1.0,
        }
    )


#: Bands per role. The overview has to explain the site, so it tolerates a smaller subject and
#: more ground; a hero shot exists to make the building look good and cannot be mostly apron.
ROLE_OBJECTIVES: dict[ViewRole, RoleObjective] = {
    ViewRole.OVERALL: RoleObjective(
        subject_share=(0.18, 0.45),
        ground_share=(0.10, 0.40),
        minimum_legible_roles=5,
        prefers_corner=True,
    ),
    ViewRole.DETAIL: RoleObjective(
        subject_share=(0.18, 0.45),
        ground_share=(0.10, 0.40),
        minimum_legible_roles=5,
        prefers_corner=True,
    ),
    ViewRole.CONTEXT: RoleObjective(
        subject_share=(0.15, 0.45),
        ground_share=(0.10, 0.40),
        minimum_legible_roles=3,
        prefers_corner=True,
    ),
    ViewRole.HERO: RoleObjective(
        subject_share=(0.30, 0.65),
        ground_share=(0.10, 0.35),
        minimum_legible_roles=3,
        prefers_corner=True,
    ),
    ViewRole.OFFICE_HERO: RoleObjective(
        subject_share=(0.30, 0.70),
        ground_share=(0.08, 0.32),
        minimum_legible_roles=2,
        prefers_corner=True,
        requires_role_target=True,
    ),
    ViewRole.LOADING_DETAIL: RoleObjective(
        subject_share=(0.28, 0.65),
        ground_share=(0.12, 0.40),
        minimum_legible_roles=2,
        prefers_corner=False,
        requires_role_target=True,
    ),
}


def _band_score(value: float, band: tuple[float, float]) -> float:
    """1 inside the band, falling off smoothly outside it, never below 0."""

    low, high = band
    if low <= value <= high:
        return 1.0
    width = max(high - low, 1e-6)
    distance = (low - value) if value < low else (value - high)
    return max(0.0, 1.0 - distance / width)


def score_candidate(score: CandidateScore, objective: RoleObjective) -> float:
    """Combine the measured quantities into one comparable number for this role.

    Occlusion and a missing role target are the only terms that can drive the result to zero:
    a camera that cannot see what its slot exists to show is not a worse photograph, it is the
    wrong photograph.
    """

    if not score.feasible:
        return 0.0
    if objective.requires_role_target and score.role_targets_visible <= 0.0:
        return 0.0
    # A camera that barely sees the project cannot be rescued by the other terms. Measured on the
    # first candidate pool, a frame showing 1.8% subject still scored 0.53, because it collected
    # full marks for having no occlusion — it had nothing to occlude — and the weighted average
    # carried it. The subject term therefore gates the rest rather than averaging into it.
    subject = _band_score(score.subject_share, objective.subject_share)
    if subject <= 0.0:
        return 0.0
    weights = objective.weights
    terms = {
        "ground": _band_score(score.ground_share, objective.ground_share),
        "roles": min(1.0, score.legible_roles / max(1, objective.minimum_legible_roles)),
        "corner": score.corner_balance if objective.prefers_corner else 1.0,
        "occlusion": max(0.0, 1.0 - score.occlusion / 0.12),
        "target": 1.0
        if not objective.requires_role_target
        else min(1.0, score.role_targets_visible / 0.01),
    }
    total = sum(weights.get(name, 0.0) for name in terms)
    supporting = sum(terms[name] * weights.get(name, 0.0) for name in terms) / max(total, 1e-6)
    return subject * supporting


def _bearing_to_offset(bearing_deg: float, distance: float) -> tuple[float, float]:
    radians = math.radians(bearing_deg)
    return distance * math.sin(radians), distance * math.cos(radians)


def propose_candidates(
    role: ViewRole,
    framing: RoleFraming,
    bounds: Bounds,
    target: Vector3,
    *,
    bearings: tuple[float, ...] = (20.0, 65.0, 110.0, 155.0, 200.0, 245.0, 290.0, 335.0),
    distance_factors: tuple[float, ...] = (0.85, 1.0, 1.25),
    elevation_offsets: tuple[float, ...] = (-6.0, 0.0, 8.0),
    maximum_clearance_m: float | None = None,
    respect_eye_height: bool = False,
) -> tuple[CameraCandidate, ...]:
    """Sweep bearing, distance and elevation around the analytic framing solution.

    The analytic solver already answers "how far back does this lens have to stand", so the sweep
    starts from its answer rather than from an arbitrary radius. What it cannot answer is which
    side of the building to stand on, and that is exactly what varies between sites.
    """

    minimum, maximum = bounds
    height = maximum[2] - minimum[2]
    eye = framing.eye_height_m or 1.7
    candidates: list[CameraCandidate] = []
    for bearing in bearings:
        angle = math.radians(bearing)
        width = (maximum[0] - minimum[0]) * abs(math.cos(angle)) + (maximum[1] - minimum[1]) * abs(
            math.sin(angle)
        )
        depth = (maximum[0] - minimum[0]) * abs(math.sin(angle)) + (maximum[1] - minimum[1]) * abs(
            math.cos(angle)
        )
        solved = (
            framed_distance(
                ((0.0, 0.0, 0.0), (width, width, height)),
                camera_height_m=eye,
                tilt_deg=framing.elevation_deg,
                focal_length_mm=framing.focal_length_mm,
                target_width_coverage=framing.target_width_coverage,
                roofline_margin=framing.roofline_margin,
            )
            + depth / 2
        )
        for factor in distance_factors:
            distance = solved * factor
            if maximum_clearance_m is not None:
                distance = min(distance, maximum_clearance_m)
            if distance <= 1.0:
                continue
            for offset in elevation_offsets:
                elevation = framing.elevation_deg + offset
                if elevation < 0.0 or elevation > 80.0:
                    continue
                east, north = _bearing_to_offset(bearing, distance)
                rise = distance * math.tan(math.radians(elevation))
                if respect_eye_height and framing.eye_height_m is not None:
                    # New source-only policy: ground roles keep their declared eye height.
                    # Legacy searches retain their existing elevation-based placement.
                    rise = 0.0
                position = (
                    target[0] + east,
                    target[1] + north,
                    minimum[2] + eye + rise,
                )
                candidates.append(
                    CameraCandidate(
                        candidate_id=(
                            f"{role.value}-b{int(bearing):03d}"
                            f"-d{round(distance):04d}-e{round(elevation):02d}"
                        ),
                        role=role,
                        position=position,
                        target=target,
                        focal_length_mm=framing.focal_length_mm,
                        bearing_deg=bearing,
                        elevation_deg=elevation,
                        distance_m=distance,
                    )
                )
    return tuple(candidates)


def _angular_gap(first: float, second: float) -> float:
    gap = abs(first - second) % 360.0
    return min(gap, 360.0 - gap)


def select_view_set(
    ranked: dict[ViewRole, list[tuple[CameraCandidate, float]]],
    *,
    minimum_bearing_gap_deg: float = 35.0,
) -> tuple[CameraCandidate, ...]:
    """Choose one camera per role, penalising a set that keeps photographing the same thing.

    Picking each role's maximum independently produces a set where the overview and the detail
    aerial stand a few degrees apart and show the same roofs. The client paid for six views, not
    for one view six times, so a candidate that repeats a bearing already taken is penalised and
    a more distinct runner-up wins its slot.
    """

    chosen: list[CameraCandidate] = []
    for role in sorted(ranked, key=lambda item: item.value):
        options = sorted(
            (item for item in ranked[role] if item[1] > 0), key=lambda item: item[1], reverse=True
        )
        if not options:
            continue
        best: tuple[CameraCandidate, float] | None = None
        for candidate, score in options:
            penalty = 0.0
            for taken in chosen:
                gap = _angular_gap(candidate.bearing_deg, taken.bearing_deg)
                if gap < minimum_bearing_gap_deg:
                    penalty += (minimum_bearing_gap_deg - gap) / minimum_bearing_gap_deg
            adjusted = score - 0.25 * penalty
            if best is None or adjusted > best[1]:
                best = (candidate, adjusted)
        if best is not None:
            chosen.append(best[0])
    return tuple(chosen)
