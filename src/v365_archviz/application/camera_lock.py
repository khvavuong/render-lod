"""Measure whether a generated image still stands on the camera the base render was made from.

`edge_alignment_f1` was used for this and answers a different question. Measured on the reference
view set, a view that kept its camera exactly — same bearing, same horizon, same background tower
— scored 0.35, because profiled cladding carries dozens of vertical ribs and redrawing them a few
pixels apart collapses the score. A view whose camera had been replaced by a drone shot scored
about the same. The two situations are opposite and that metric cannot separate them.

What separates them is the camera itself. Project points whose world position is known through the
stored camera matrix, find where they land in each image, and compare. A camera that was kept
moves landmarks slightly and uniformly; a camera that was rebuilt moves them a long way, and with
a systematic scale or shift the residual exposes.

This module owns the projection and the verdict. Locating a landmark inside the generated image is
the caller's job, because that needs either the instance pass or a feature matcher.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

Vector3 = tuple[float, float, float]
Pixel = tuple[float, float]


@dataclass(frozen=True, slots=True)
class CameraPose:
    """The stored pose a base render was made from."""

    position: Vector3
    target: Vector3
    focal_length_mm: float
    sensor_width_mm: float = 36.0
    aspect_ratio: float = 16 / 9


@dataclass(frozen=True, slots=True)
class CameraLockVerdict:
    """How far the generated image drifted from the pose it was conditioned on."""

    landmark_count: int
    median_offset_px: float
    max_offset_px: float
    #: Uniform component of the drift. A pan or a crop shows up here.
    systematic_offset_px: float
    #: Spread around the uniform component. A rebuilt camera shows up here.
    residual_offset_px: float
    tolerance_px: float

    @property
    def status(self) -> str:
        if self.landmark_count < 3:
            return "unverifiable"
        if self.residual_offset_px > self.tolerance_px:
            return "camera_rebuilt"
        if self.median_offset_px > self.tolerance_px:
            return "camera_shifted"
        return "camera_held"


def _normalise(vector: Vector3) -> Vector3:
    length = math.sqrt(sum(component * component for component in vector))
    if length <= 1e-9:
        raise ValueError("vector must be non-zero")
    return (vector[0] / length, vector[1] / length, vector[2] / length)


def _cross(first: Vector3, second: Vector3) -> Vector3:
    return (
        first[1] * second[2] - first[2] * second[1],
        first[2] * second[0] - first[0] * second[2],
        first[0] * second[1] - first[1] * second[0],
    )


def _dot(first: Vector3, second: Vector3) -> float:
    return sum(a * b for a, b in zip(first, second, strict=True))


def project(pose: CameraPose, point: Vector3, width_px: int, height_px: int) -> Pixel | None:
    """Pixel a world point lands on, or None when it sits behind the camera."""

    forward = _normalise(
        (
            pose.target[0] - pose.position[0],
            pose.target[1] - pose.position[1],
            pose.target[2] - pose.position[2],
        )
    )
    right = _normalise(_cross(forward, (0.0, 0.0, 1.0)))
    up = _normalise(_cross(right, forward))
    delta = (
        point[0] - pose.position[0],
        point[1] - pose.position[1],
        point[2] - pose.position[2],
    )
    depth = _dot(delta, forward)
    if depth <= 1e-6:
        return None
    horizontal_tangent = pose.sensor_width_mm / (2 * pose.focal_length_mm)
    vertical_tangent = horizontal_tangent / pose.aspect_ratio
    x_ndc = _dot(delta, right) / (depth * horizontal_tangent)
    y_ndc = _dot(delta, up) / (depth * vertical_tangent)
    return (
        (x_ndc + 1.0) * 0.5 * width_px,
        (1.0 - y_ndc) * 0.5 * height_px,
    )


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def evaluate_camera_lock(
    expected: list[Pixel],
    observed: list[Pixel],
    *,
    tolerance_px: float,
) -> CameraLockVerdict:
    """Compare where landmarks should be against where they are.

    The uniform part of the drift is reported separately from the spread. A provider that panned
    or cropped moves every landmark the same way, which is recoverable; one that rebuilt the
    camera moves them inconsistently, which is not.
    """

    if len(expected) != len(observed):
        raise ValueError("expected and observed landmark counts must match")
    if tolerance_px <= 0:
        raise ValueError("tolerance must be positive")
    if not expected:
        return CameraLockVerdict(0, 0.0, 0.0, 0.0, 0.0, tolerance_px)

    offsets = [
        (observation[0] - reference[0], observation[1] - reference[1])
        for reference, observation in zip(expected, observed, strict=True)
    ]
    distances = [math.hypot(*offset) for offset in offsets]
    mean_x = sum(offset[0] for offset in offsets) / len(offsets)
    mean_y = sum(offset[1] for offset in offsets) / len(offsets)
    residuals = [
        math.hypot(offset[0] - mean_x, offset[1] - mean_y) for offset in offsets
    ]
    return CameraLockVerdict(
        landmark_count=len(offsets),
        median_offset_px=_median(distances),
        max_offset_px=max(distances),
        systematic_offset_px=math.hypot(mean_x, mean_y),
        residual_offset_px=_median(residuals),
        tolerance_px=tolerance_px,
    )


def tolerance_for(width_px: int, fraction: float = 0.015) -> float:
    """Drift budget in pixels, expressed as a share of frame width.

    Stated relative to the frame so the same verdict holds at preview and delivery resolution.
    """

    if width_px <= 0:
        raise ValueError("frame width must be positive")
    if not 0.0 < fraction < 1.0:
        raise ValueError("fraction must be within (0, 1)")
    return width_px * fraction
