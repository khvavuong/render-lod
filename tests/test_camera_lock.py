import math

import pytest

from v365_archviz.application.camera_lock import (
    CameraPose,
    evaluate_camera_lock,
    project,
    tolerance_for,
)

POSE = CameraPose(
    position=(0.0, -100.0, 30.0),
    target=(0.0, 0.0, 5.0),
    focal_length_mm=32.0,
)
WIDTH, HEIGHT = 2048, 1152


def test_target_projects_to_the_frame_centre() -> None:
    pixel = project(POSE, POSE.target, WIDTH, HEIGHT)

    assert pixel is not None
    assert pixel[0] == pytest.approx(WIDTH / 2, abs=1e-6)
    assert pixel[1] == pytest.approx(HEIGHT / 2, abs=1e-6)


def test_points_behind_the_camera_do_not_project() -> None:
    assert project(POSE, (0.0, -400.0, 30.0), WIDTH, HEIGHT) is None


def test_a_point_to_the_right_lands_right_of_centre() -> None:
    pixel = project(POSE, (20.0, 0.0, 5.0), WIDTH, HEIGHT)

    assert pixel is not None
    assert pixel[0] > WIDTH / 2


def test_a_held_camera_reads_as_held() -> None:
    expected = [(100.0, 200.0), (900.0, 400.0), (1500.0, 800.0), (600.0, 1000.0)]
    observed = [(x + 3.0, y - 2.0) for x, y in expected]

    verdict = evaluate_camera_lock(expected, observed, tolerance_px=tolerance_for(WIDTH))

    assert verdict.status == "camera_held"
    assert verdict.residual_offset_px == pytest.approx(0.0, abs=1e-9)


def test_a_uniform_pan_is_reported_as_a_shift_not_a_rebuild() -> None:
    """Every landmark moving the same way is a crop or a pan, which stays recoverable."""

    expected = [(100.0, 200.0), (900.0, 400.0), (1500.0, 800.0), (600.0, 1000.0)]
    observed = [(x + 120.0, y + 40.0) for x, y in expected]

    verdict = evaluate_camera_lock(expected, observed, tolerance_px=tolerance_for(WIDTH))

    assert verdict.status == "camera_shifted"
    assert verdict.systematic_offset_px == pytest.approx(math.hypot(120.0, 40.0), abs=1e-6)
    assert verdict.residual_offset_px == pytest.approx(0.0, abs=1e-9)


def test_an_inconsistent_drift_is_reported_as_a_rebuild() -> None:
    expected = [(100.0, 200.0), (900.0, 400.0), (1500.0, 800.0), (600.0, 1000.0)]
    observed = [(120.0, 260.0), (700.0, 380.0), (1560.0, 300.0), (300.0, 980.0)]

    verdict = evaluate_camera_lock(expected, observed, tolerance_px=tolerance_for(WIDTH))

    assert verdict.status == "camera_rebuilt"
    assert verdict.residual_offset_px > verdict.tolerance_px


def test_too_few_landmarks_is_unverifiable_rather_than_a_pass() -> None:
    expected = [(100.0, 200.0), (900.0, 400.0)]

    verdict = evaluate_camera_lock(expected, expected, tolerance_px=tolerance_for(WIDTH))

    assert verdict.status == "unverifiable"


def test_tolerance_scales_with_the_frame() -> None:
    """The same verdict has to hold at preview and delivery resolution."""

    assert tolerance_for(768) == pytest.approx(768 * 0.015)
    assert tolerance_for(2752) == pytest.approx(2752 * 0.015)


def test_mismatched_inputs_are_rejected() -> None:
    with pytest.raises(ValueError):
        evaluate_camera_lock([(0.0, 0.0)], [], tolerance_px=10.0)
    with pytest.raises(ValueError):
        evaluate_camera_lock([(0.0, 0.0)], [(0.0, 0.0)], tolerance_px=0.0)
    with pytest.raises(ValueError):
        tolerance_for(0)
