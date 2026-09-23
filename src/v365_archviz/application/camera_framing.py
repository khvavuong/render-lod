"""Closed-form framing constraints for camera placement.

Camera distances used to be tuned by hand against one model, which made them wrong for any site
with a different proportion. These helpers state the constraint instead of its answer, so the
same rule holds for a 350 m shed row and a 40 m unit alike.

Everything here is analytic: no render is needed, and nothing depends on occlusion. Quantities
that do depend on occlusion — how much of the frame the subject actually covers once trees and
neighbouring volumes are in the way — are measured downstream by the conditioning gate.
"""

from __future__ import annotations

import math

Vector3 = tuple[float, float, float]
Bounds = tuple[Vector3, Vector3]


def half_fov_deg(
    focal_length_mm: float,
    sensor_width_mm: float = 36.0,
    aspect_ratio: float = 16 / 9,
) -> tuple[float, float]:
    """Return the horizontal and vertical half angles of a rectilinear lens, in degrees."""

    if focal_length_mm <= 0 or sensor_width_mm <= 0 or aspect_ratio <= 0:
        raise ValueError("lens geometry must be positive")
    horizontal = math.degrees(math.atan(sensor_width_mm / (2 * focal_length_mm)))
    sensor_height_mm = sensor_width_mm / aspect_ratio
    vertical = math.degrees(math.atan(sensor_height_mm / (2 * focal_length_mm)))
    return horizontal, vertical


def distance_for_roofline(
    subject_height_m: float,
    camera_height_m: float,
    tilt_deg: float,
    focal_length_mm: float,
    *,
    sensor_width_mm: float = 36.0,
    aspect_ratio: float = 16 / 9,
    margin: float = 0.85,
) -> float:
    """Shortest distance at which the top of the subject still sits inside the frame.

    A clipped parapet is not a frame a photographer would keep, and a provider asked to
    photorealise one answers by moving the camera itself. `margin` keeps the roofline inside the
    frame edge rather than exactly on it.
    """

    if not 0.0 < margin <= 1.0:
        raise ValueError("margin must be within (0, 1]")
    rise = subject_height_m - camera_height_m
    if rise <= 0:
        return 0.0
    _, vertical = half_fov_deg(focal_length_mm, sensor_width_mm, aspect_ratio)
    limit_deg = tilt_deg + vertical * margin
    if limit_deg <= 0.0:
        raise ValueError("camera cannot frame anything above it at this tilt")
    if limit_deg >= 90.0:
        return 0.0
    return rise / math.tan(math.radians(limit_deg))


def distance_for_width_coverage(
    subject_width_m: float,
    coverage: float,
    focal_length_mm: float,
    *,
    sensor_width_mm: float = 36.0,
) -> float:
    """Distance at which the subject spans `coverage` of the frame width.

    Used as the starting point for a role's target subject share. It ignores occlusion and
    foreshortening, so it is an upper bound on how much of the frame the subject can fill; the
    conditioning gate measures what actually survives.
    """

    if not 0.0 < coverage <= 1.0:
        raise ValueError("coverage must be within (0, 1]")
    if subject_width_m <= 0:
        raise ValueError("subject width must be positive")
    horizontal, _ = half_fov_deg(focal_length_mm, sensor_width_mm)
    return subject_width_m / (2 * coverage * math.tan(math.radians(horizontal)))


def tilt_for_foreground_share(
    share: float,
    focal_length_mm: float,
    *,
    sensor_width_mm: float = 36.0,
    aspect_ratio: float = 16 / 9,
) -> float:
    """Upward tilt that leaves at most `share` of the frame height below the horizon.

    A level eye-level camera puts the horizon across the middle of the frame, so half the image
    becomes featureless apron. Tilting up moves the horizon down.
    """

    if not 0.0 < share < 1.0:
        raise ValueError("share must be within (0, 1)")
    _, vertical = half_fov_deg(focal_length_mm, sensor_width_mm, aspect_ratio)
    # The horizon sits at the tilt angle; it reaches the lower frame edge at tilt == vertical.
    return vertical * (1.0 - 2.0 * share)


def elevation_direction(
    horizontal: tuple[float, float],
    elevation_deg: float,
) -> Vector3:
    """Unit direction from target to camera at the requested elevation above the ground plane."""

    length = math.hypot(*horizontal)
    if length <= 1e-9:
        raise ValueError("horizontal bearing must be non-zero")
    rise = length * math.tan(math.radians(elevation_deg))
    magnitude = math.sqrt(length * length + rise * rise)
    return (horizontal[0] / magnitude, horizontal[1] / magnitude, rise / magnitude)


def framed_distance(
    bounds: Bounds,
    *,
    camera_height_m: float,
    tilt_deg: float,
    focal_length_mm: float,
    target_width_coverage: float,
    roofline_margin: float = 0.85,
    sensor_width_mm: float = 36.0,
    aspect_ratio: float = 16 / 9,
) -> float:
    """Distance satisfying both the roofline and the subject-share constraints.

    The roofline constraint is a floor and the coverage target is a preference, so the result is
    whichever is further out. Returning the coverage distance alone would clip the roof on a tall
    subject; returning the roofline distance alone would leave a small subject adrift in frame.
    """

    minimum, maximum = bounds
    width = max(maximum[0] - minimum[0], maximum[1] - minimum[1])
    height = maximum[2] - minimum[2]
    roofline = distance_for_roofline(
        height,
        camera_height_m,
        tilt_deg,
        focal_length_mm,
        sensor_width_mm=sensor_width_mm,
        aspect_ratio=aspect_ratio,
        margin=roofline_margin,
    )
    coverage = distance_for_width_coverage(
        width,
        target_width_coverage,
        focal_length_mm,
        sensor_width_mm=sensor_width_mm,
    )
    return max(roofline, coverage)


def focal_length_for_roofline(
    subject_height_m: float,
    camera_height_m: float,
    tilt_deg: float,
    distance_m: float,
    *,
    sensor_width_mm: float = 36.0,
    aspect_ratio: float = 16 / 9,
    margin: float = 0.85,
) -> float:
    """Longest lens that still holds the roofline from a distance the site fixes.

    The inverse of `distance_for_roofline`, for the case where the site answers first: a yard is
    only so deep, so the camera cannot back out to the distance the pack asked for. Keeping the
    pack's lens there clips the parapet, and a provider handed a clipped frame reframes the shot
    itself, which is the one thing the geometry contract forbids. Widening instead keeps the
    building whole inside the camera the system owns.
    """

    if distance_m <= 0:
        raise ValueError("distance must be positive")
    if not 0.0 < margin <= 1.0:
        raise ValueError("margin must be within (0, 1]")
    rise = subject_height_m - camera_height_m
    if rise <= 0:
        return math.inf
    limit_deg = math.degrees(math.atan(rise / distance_m))
    vertical_deg = (limit_deg - tilt_deg) / margin
    if vertical_deg <= 0.0:
        # Tilt alone already reaches past the roofline; any lens holds it.
        return math.inf
    if vertical_deg >= 90.0:
        raise ValueError("no rectilinear lens frames this subject from this distance")
    sensor_height_mm = sensor_width_mm / aspect_ratio
    return sensor_height_mm / (2 * math.tan(math.radians(vertical_deg)))


def focal_length_for_width_coverage(
    subject_width_m: float,
    coverage: float,
    distance_m: float,
    *,
    sensor_width_mm: float = 36.0,
) -> float:
    """Lens at which the subject spans `coverage` of the frame width from a fixed distance."""

    if distance_m <= 0:
        raise ValueError("distance must be positive")
    if not 0.0 < coverage <= 1.0:
        raise ValueError("coverage must be within (0, 1]")
    if subject_width_m <= 0:
        raise ValueError("subject width must be positive")
    half_width_tan = subject_width_m / (2 * coverage * distance_m)
    return sensor_width_mm / (2 * half_width_tan)


def framed_focal_length(
    bounds: Bounds,
    *,
    camera_height_m: float,
    tilt_deg: float,
    distance_m: float,
    target_width_coverage: float,
    roofline_margin: float = 0.85,
    minimum_focal_length_mm: float = 18.0,
    sensor_width_mm: float = 36.0,
    aspect_ratio: float = 16 / 9,
) -> float:
    """Widest-needed lens that satisfies both framing constraints at a fixed distance.

    Whichever constraint needs the wider lens wins, because a lens that holds the roofline but
    crops the width fails just as visibly as the reverse. The floor is a real limit rather than a
    preference: below roughly 18 mm a full-frame rectilinear lens bends verticals enough that the
    result stops reading as architectural photography, and a site that cannot be photographed
    from its own apron is a finding for the conditioning gate, not something to widen away.
    """

    minimum, maximum = bounds
    width = max(maximum[0] - minimum[0], maximum[1] - minimum[1])
    height = maximum[2] - minimum[2]
    roofline = focal_length_for_roofline(
        height,
        camera_height_m,
        tilt_deg,
        distance_m,
        sensor_width_mm=sensor_width_mm,
        aspect_ratio=aspect_ratio,
        margin=roofline_margin,
    )
    coverage = focal_length_for_width_coverage(
        width,
        target_width_coverage,
        distance_m,
        sensor_width_mm=sensor_width_mm,
    )
    return max(minimum_focal_length_mm, min(roofline, coverage))


def tilt_for_roofline(
    subject_height_m: float,
    camera_height_m: float,
    distance_m: float,
    focal_length_mm: float,
    *,
    sensor_width_mm: float = 36.0,
    aspect_ratio: float = 16 / 9,
    margin: float = 0.85,
) -> float:
    """Upward tilt that brings the roofline inside the frame from a fixed distance and lens.

    The last constraint left when both distance and lens have run out. A photographer standing in
    a yard that is too shallow, already on the widest lens they will accept, tilts the camera up;
    the cost is foreground, which `tilt_for_foreground_share` bounds from the other side.
    """

    if distance_m <= 0:
        raise ValueError("distance must be positive")
    if not 0.0 < margin <= 1.0:
        raise ValueError("margin must be within (0, 1]")
    rise = subject_height_m - camera_height_m
    if rise <= 0:
        return 0.0
    _, vertical = half_fov_deg(focal_length_mm, sensor_width_mm, aspect_ratio)
    limit_deg = math.degrees(math.atan(rise / distance_m))
    return max(0.0, limit_deg - vertical * margin)


#: How close to the lens a point may be and still be projected. A target that
#: straddles this plane is clamped rather than dropped, so it reads as filling
#: the frame, which from that distance it does.
NEAR_PLANE_M = 0.05


def _camera_basis(
    position: Vector3, target: Vector3
) -> tuple[Vector3, Vector3, Vector3] | None:
    """Forward, right and up of a camera aimed at a target, or None if degenerate."""

    forward = tuple(target[axis] - position[axis] for axis in range(3))
    length = math.sqrt(sum(value * value for value in forward))
    if length <= 1e-9:
        return None
    forward = tuple(value / length for value in forward)
    world_up = (0.0, 0.0, 1.0)
    right = (
        forward[1] * world_up[2] - forward[2] * world_up[1],
        forward[2] * world_up[0] - forward[0] * world_up[2],
        forward[0] * world_up[1] - forward[1] * world_up[0],
    )
    span = math.sqrt(sum(value * value for value in right))
    # Straight down or straight up: any horizontal right vector will do.
    right = (1.0, 0.0, 0.0) if span <= 1e-9 else tuple(value / span for value in right)
    up = (
        right[1] * forward[2] - right[2] * forward[1],
        right[2] * forward[0] - right[0] * forward[2],
        right[0] * forward[1] - right[1] * forward[0],
    )
    return forward, right, up  # type: ignore[return-value]


def _convex_hull(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Andrew's monotone chain, counter-clockwise, without repeating the first point."""

    ordered = sorted(set(points))
    if len(ordered) < 3:
        return ordered

    def build(sequence: list[tuple[float, float]]) -> list[tuple[float, float]]:
        chain: list[tuple[float, float]] = []
        for point in sequence:
            while len(chain) >= 2:
                (x0, y0), (x1, y1) = chain[-2], chain[-1]
                cross = (x1 - x0) * (point[1] - y0) - (y1 - y0) * (point[0] - x0)
                if cross > 0:
                    break
                chain.pop()
            chain.append(point)
        return chain

    lower = build(ordered)
    upper = build(list(reversed(ordered)))
    return lower[:-1] + upper[:-1]


def _clip_half_plane(
    polygon: list[tuple[float, float]], axis: int, boundary: float, keep_above: bool
) -> list[tuple[float, float]]:
    """Sutherland-Hodgman against one edge of the frame."""

    if not polygon:
        return []
    other = 1 - axis
    clipped: list[tuple[float, float]] = []
    for index, current in enumerate(polygon):
        previous = polygon[index - 1]
        current_in = current[axis] >= boundary if keep_above else current[axis] <= boundary
        previous_in = previous[axis] >= boundary if keep_above else previous[axis] <= boundary
        if current_in != previous_in:
            span = current[axis] - previous[axis]
            if abs(span) > 1e-12:
                ratio = (boundary - previous[axis]) / span
                crossing = [0.0, 0.0]
                crossing[axis] = boundary
                crossing[other] = previous[other] + (current[other] - previous[other]) * ratio
                clipped.append((crossing[0], crossing[1]))
        if current_in:
            clipped.append(current)
    return clipped


def _clip_to_frame(polygon: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Keep only the part of a projected shape the frame actually contains."""

    for axis, boundary, keep_above in (
        (0, -1.0, True),
        (0, 1.0, False),
        (1, -1.0, True),
        (1, 1.0, False),
    ):
        polygon = _clip_half_plane(polygon, axis, boundary, keep_above)
        if not polygon:
            return []
    return polygon


def _polygon_area(polygon: list[tuple[float, float]]) -> float:
    if len(polygon) < 3:
        return 0.0
    total = 0.0
    for index, (x0, y0) in enumerate(polygon):
        x1, y1 = polygon[index - 1]
        total += x1 * y0 - x0 * y1
    return abs(total) / 2


def _projected_polygon(
    position: Vector3,
    target: Vector3,
    bounds: Bounds,
    focal_length_mm: float,
    sensor_width_mm: float,
    aspect_ratio: float,
) -> list[tuple[float, float]]:
    """What share of the frame a box would fill if nothing stood in front of it.

    This is the prediction a threshold can be derived from instead of written
    down. A dock door four metres wide and a service yard two thousand square
    metres in plan cannot be asked for the same share of a frame, and a constant
    that suits one rejects a model whose only evidence is the other — which is
    how a correctly framed logistics view came to be refused on a model that had
    eighteen dock doors and no apron. What both can be asked for is that they
    show up in something like the proportion the geometry says they should.

    Occlusion is deliberately not modelled: the gap between this number and what
    the render actually shows is the useful signal, not an error.
    """

    basis = _camera_basis(position, target)
    if basis is None:
        return []
    forward, right, up = basis
    horizontal, vertical = half_fov_deg(focal_length_mm, sensor_width_mm, aspect_ratio)
    tan_horizontal = math.tan(math.radians(horizontal))
    tan_vertical = math.tan(math.radians(vertical))
    minimum, maximum = bounds
    projected: list[tuple[float, float]] = []
    ahead = False
    for corner in (
        (minimum[0], minimum[1], minimum[2]),
        (minimum[0], minimum[1], maximum[2]),
        (minimum[0], maximum[1], minimum[2]),
        (minimum[0], maximum[1], maximum[2]),
        (maximum[0], minimum[1], minimum[2]),
        (maximum[0], minimum[1], maximum[2]),
        (maximum[0], maximum[1], minimum[2]),
        (maximum[0], maximum[1], maximum[2]),
    ):
        offset = tuple(corner[axis] - position[axis] for axis in range(3))
        depth = sum(offset[axis] * forward[axis] for axis in range(3))
        if depth >= NEAR_PLANE_M:
            ahead = True
        else:
            depth = NEAR_PLANE_M
        across = sum(offset[axis] * right[axis] for axis in range(3))
        above = sum(offset[axis] * up[axis] for axis in range(3))
        projected.append(
            (across / (depth * tan_horizontal), above / (depth * tan_vertical))
        )
    if not ahead:
        # Entirely behind the lens. Clamping every corner to the near plane would
        # otherwise report it as filling the frame.
        return []
    return _clip_to_frame(_convex_hull(projected))


def projected_frame_fraction(
    position: Vector3,
    target: Vector3,
    bounds: Bounds,
    focal_length_mm: float,
    *,
    sensor_width_mm: float = 36.0,
    aspect_ratio: float = 16 / 9,
) -> float:
    """What share of the frame one box would fill if nothing stood in front of it."""

    polygon = _projected_polygon(
        position, target, bounds, focal_length_mm, sensor_width_mm, aspect_ratio
    )
    # The frame itself spans two units on each axis.
    return min(1.0, _polygon_area(polygon) / 4.0)


#: Resolution the union is counted on. Coarse on purpose: the answer is compared
#: against a rendered coverage as a ratio, and a hundredth of a frame is finer
#: than any threshold that ratio feeds.
UNION_GRID = (128, 72)


def _contains(polygon: list[tuple[float, float]], x: float, y: float) -> bool:
    """Whether a convex, counter-clockwise polygon contains a point."""

    for index, (x0, y0) in enumerate(polygon):
        x1, y1 = polygon[(index + 1) % len(polygon)]
        if (x1 - x0) * (y - y0) - (y1 - y0) * (x - x0) < -1e-12:
            return False
    return True


def projected_frame_union(
    position: Vector3,
    target: Vector3,
    boxes: list[Bounds],
    focal_length_mm: float,
    *,
    sensor_width_mm: float = 36.0,
    aspect_ratio: float = 16 / 9,
) -> float:
    """What share of the frame a set of boxes would fill between them, counted once.

    Adding the boxes up instead would make the answer depend on how many volumes
    a modeller happened to draw for one thing: eighteen overlapping landscape
    slabs would predict half a frame of planting where there is a quarter, and
    the ratio a threshold reads from it would move with the model rather than
    with the photograph.
    """

    polygons = [
        polygon
        for box in boxes
        if (
            polygon := _projected_polygon(
                position, target, box, focal_length_mm, sensor_width_mm, aspect_ratio
            )
        )
    ]
    if not polygons:
        return 0.0
    columns, rows = UNION_GRID
    covered = 0
    for row in range(rows):
        y = -1.0 + (row + 0.5) * 2.0 / rows
        for column in range(columns):
            x = -1.0 + (column + 0.5) * 2.0 / columns
            if any(_contains(polygon, x, y) for polygon in polygons):
                covered += 1
    return covered / (columns * rows)
