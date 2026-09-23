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
