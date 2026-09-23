import math

import pytest

from v365_archviz.application.camera_framing import (
    distance_for_roofline,
    distance_for_width_coverage,
    elevation_direction,
    focal_length_for_roofline,
    focal_length_for_width_coverage,
    framed_distance,
    framed_focal_length,
    half_fov_deg,
    tilt_for_foreground_share,
    tilt_for_roofline,
)


def test_half_fov_matches_the_lens_equation() -> None:
    horizontal, vertical = half_fov_deg(35.0)

    assert horizontal == pytest.approx(math.degrees(math.atan(18 / 35)), abs=1e-9)
    assert vertical == pytest.approx(math.degrees(math.atan((18 * 9 / 16) / 35)), abs=1e-9)


def test_roofline_distance_puts_the_top_inside_the_frame() -> None:
    height, camera, tilt, focal = 11.0, 1.9, 3.3, 35.0

    distance = distance_for_roofline(height, camera, tilt, focal, margin=0.85)

    top_angle = math.degrees(math.atan((height - camera) / distance))
    _, vertical = half_fov_deg(focal)
    assert top_angle <= tilt + vertical


def test_roofline_distance_scales_with_the_subject_not_a_tuned_constant() -> None:
    """The same rule has to hold for a low shed and a tall unit, which a fixed metre band cannot."""

    low = distance_for_roofline(11.0, 1.8, 0.0, 35.0)
    tall = distance_for_roofline(25.0, 1.8, 0.0, 35.0)

    assert tall > low
    # Height above the camera roughly doubles, so the required stand-off roughly doubles too.
    assert tall / low == pytest.approx((25.0 - 1.8) / (11.0 - 1.8), rel=1e-6)


def test_subject_below_the_camera_needs_no_stand_off() -> None:
    assert distance_for_roofline(2.0, 40.0, -20.0, 28.0) == 0.0


def test_width_coverage_distance_is_exact() -> None:
    width, coverage, focal = 60.0, 0.5, 32.0

    distance = distance_for_width_coverage(width, coverage, focal)

    horizontal, _ = half_fov_deg(focal)
    visible_width = 2 * distance * math.tan(math.radians(horizontal))
    assert width / visible_width == pytest.approx(coverage, rel=1e-9)


def test_tilt_for_foreground_share_moves_the_horizon_down() -> None:
    focal = 32.0
    _, vertical = half_fov_deg(focal)

    level = tilt_for_foreground_share(0.5, focal)
    quarter = tilt_for_foreground_share(0.25, focal)

    # Half the frame below the horizon is exactly a level camera.
    assert level == pytest.approx(0.0, abs=1e-9)
    # Less apron means tilting up.
    assert quarter == pytest.approx(vertical * 0.5, rel=1e-9)
    assert quarter > level


def test_elevation_direction_has_the_requested_elevation() -> None:
    for elevation in (10.0, 28.0, 45.0):
        direction = elevation_direction((-1.0, -0.85), elevation)
        length = math.sqrt(sum(component * component for component in direction))
        assert length == pytest.approx(1.0, abs=1e-9)
        assert math.degrees(math.asin(direction[2])) == pytest.approx(elevation, abs=1e-9)


def test_framed_distance_respects_whichever_constraint_binds() -> None:
    tall = ((0.0, 0.0, 0.0), (20.0, 20.0, 30.0))
    wide = ((0.0, 0.0, 0.0), (300.0, 120.0, 8.0))
    common = dict(
        camera_height_m=1.8,
        tilt_deg=2.0,
        focal_length_mm=32.0,
        target_width_coverage=0.6,
    )

    tall_distance = framed_distance(tall, **common)
    wide_distance = framed_distance(wide, **common)

    # A tall narrow subject is held back by its roofline, a long low one by its width.
    assert tall_distance == pytest.approx(
        distance_for_roofline(30.0, 1.8, 2.0, 32.0, margin=0.85), rel=1e-9
    )
    assert wide_distance == pytest.approx(
        distance_for_width_coverage(300.0, 0.6, 32.0), rel=1e-9
    )


def test_invalid_inputs_are_rejected() -> None:
    with pytest.raises(ValueError):
        half_fov_deg(0.0)
    with pytest.raises(ValueError):
        distance_for_width_coverage(10.0, 0.0, 35.0)
    with pytest.raises(ValueError):
        tilt_for_foreground_share(1.0, 35.0)
    with pytest.raises(ValueError):
        elevation_direction((0.0, 0.0), 20.0)


def test_focal_length_for_roofline_inverts_the_distance_solver() -> None:
    """The two directions have to agree, or a fitted frame and a rendered frame drift apart."""

    for focal_length in (24.0, 35.0, 50.0):
        distance = distance_for_roofline(15.0, 1.7, 6.0, focal_length)
        assert focal_length_for_roofline(15.0, 1.7, 6.0, distance) == pytest.approx(
            focal_length, rel=1e-9
        )


def test_focal_length_for_width_coverage_inverts_its_distance_solver() -> None:
    for focal_length in (24.0, 35.0):
        distance = distance_for_width_coverage(40.0, 0.7, focal_length)
        assert focal_length_for_width_coverage(40.0, 0.7, distance) == pytest.approx(
            focal_length, rel=1e-9
        )


def test_a_camera_above_the_subject_needs_no_lens_to_hold_the_roofline() -> None:
    assert focal_length_for_roofline(3.0, 8.0, 0.0, 20.0) == math.inf


def test_framed_focal_length_takes_whichever_constraint_needs_the_wider_lens() -> None:
    bounds = ((0.0, 0.0, 0.0), (15.0, 15.0, 15.0))
    solved = framed_focal_length(
        bounds,
        camera_height_m=1.85,
        tilt_deg=6.0,
        distance_m=23.6,
        target_width_coverage=0.72,
        minimum_focal_length_mm=8.0,
    )
    roofline = focal_length_for_roofline(15.0, 1.85, 6.0, 23.6)
    coverage = focal_length_for_width_coverage(15.0, 0.72, 23.6)
    assert solved == pytest.approx(min(roofline, coverage))


def test_framed_focal_length_never_goes_below_the_architectural_floor() -> None:
    """A site too tight to photograph is a finding, not a licence to reach for a fisheye."""

    solved = framed_focal_length(
        ((0.0, 0.0, 0.0), (40.0, 40.0, 40.0)),
        camera_height_m=1.7,
        tilt_deg=0.0,
        distance_m=12.0,
        target_width_coverage=0.8,
        minimum_focal_length_mm=18.0,
    )
    assert solved == pytest.approx(18.0)


def test_tilt_for_roofline_brings_a_clipped_parapet_back_into_frame() -> None:
    tilt = tilt_for_roofline(15.0, 1.85, 23.6, 18.0)

    assert tilt > 0.0
    assert distance_for_roofline(15.0, 1.85, tilt, 18.0) == pytest.approx(23.6, rel=1e-9)


def test_no_tilt_is_needed_when_the_lens_already_holds_the_roofline() -> None:
    assert tilt_for_roofline(11.0, 1.7, 200.0, 24.0) == pytest.approx(0.0)
