"""Deterministic standard camera planning for an industrial campus."""

from __future__ import annotations

from pathlib import Path

from v365_archviz.artifacts import atomic_write
from v365_archviz.domain.scene import CanonicalScene, SceneElement, SemanticRole
from v365_archviz.domain.workflow import Camera, ViewRole, ViewSet


def _center(element: SceneElement) -> tuple[float, float, float]:
    return tuple(
        (low + high) / 2
        for low, high in zip(
            element.bounding_box.minimum, element.bounding_box.maximum, strict=True
        )
    )  # type: ignore[return-value]


def _scene_bounds(
    scene: CanonicalScene,
) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    minimum = tuple(
        min(element.bounding_box.minimum[index] for element in scene.elements)
        for index in range(3)
    )
    maximum = tuple(
        max(element.bounding_box.maximum[index] for element in scene.elements)
        for index in range(3)
    )
    return minimum, maximum  # type: ignore[return-value]


def _frontmost(scene: CanonicalScene, role: SemanticRole) -> SceneElement:
    candidates = [element for element in scene.elements if element.semantic_role is role]
    if not candidates:
        candidates = list(scene.elements)
    return min(
        candidates,
        key=lambda element: (element.bounding_box.minimum[1], _center(element)[0]),
    )


class PlanStandardCameras:
    def execute(self, scene_path: Path) -> ViewSet:
        scene = CanonicalScene.model_validate_json(scene_path.read_text(encoding="utf-8"))
        minimum, maximum = _scene_bounds(scene)
        center = tuple((low + high) / 2 for low, high in zip(minimum, maximum, strict=True))
        span_x = maximum[0] - minimum[0]
        span_y = maximum[1] - minimum[1]
        span = max(span_x, span_y)

        office = _frontmost(scene, SemanticRole.OFFICE_BLOCK)
        shed = _frontmost(scene, SemanticRole.MAIN_SHED)
        office_target = _center(office)
        shed_target = _center(shed)
        cameras = (
            Camera(
                view_id="view-01",
                role=ViewRole.OVERALL,
                position=(center[0] - span * 0.85, center[1] - span * 0.9, maximum[2] + span * 0.7),
                target=(center[0], center[1], maximum[2] * 0.25),
                focal_length_mm=48,
                sensor_width_mm=36,
                aspect_ratio="16:9",
            ),
            Camera(
                view_id="view-02",
                role=ViewRole.CONTEXT,
                position=(
                    center[0] + span * 0.8,
                    minimum[1] - span * 0.65,
                    maximum[2] + span * 0.22,
                ),
                target=(center[0], center[1], maximum[2] * 0.3),
                focal_length_mm=42,
                sensor_width_mm=36,
                aspect_ratio="16:9",
            ),
            Camera(
                view_id="view-03",
                role=ViewRole.OFFICE_HERO,
                position=(office_target[0], office.bounding_box.minimum[1] - 32.0, 2.1),
                target=(office_target[0], office_target[1], min(4.0, office_target[2])),
                focal_length_mm=28,
                sensor_width_mm=36,
                aspect_ratio="16:9",
            ),
            Camera(
                view_id="view-04",
                role=ViewRole.LOADING_DETAIL,
                position=(shed_target[0] - 12.0, shed.bounding_box.minimum[1] - 28.0, 2.1),
                target=(shed_target[0], shed.bounding_box.minimum[1], min(4.5, shed_target[2])),
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
        view_set = ViewSet(
            view_set_id=f"{revision_key}-standard-v1",
            design_revision="R00-base",
            cameras=cameras,
        )
        output = scene_path.parent / "view_set.json"
        atomic_write(output, view_set.model_dump_json(indent=2).encode() + b"\n")
        return view_set
