"""Deterministic standard camera planning for an industrial campus."""

from __future__ import annotations

from pathlib import Path

from v365_archviz.artifacts import atomic_write
from v365_archviz.domain.design import DesignDNA
from v365_archviz.domain.scene import CanonicalScene, SceneElement
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
        min(element.bounding_box.minimum[index] for element in scene.elements) for index in range(3)
    )
    maximum = tuple(
        max(element.bounding_box.maximum[index] for element in scene.elements) for index in range(3)
    )
    return minimum, maximum  # type: ignore[return-value]


def _architectural_elements(scene: CanonicalScene) -> list[SceneElement]:
    candidates = [
        element
        for element in scene.elements
        if element.bounding_box.maximum[2] - element.bounding_box.minimum[2] >= 3.0
    ]
    return candidates or list(scene.elements)


def _footprint(element: SceneElement) -> float:
    bounds = element.bounding_box
    return (bounds.maximum[0] - bounds.minimum[0]) * (bounds.maximum[1] - bounds.minimum[1])


def _height(element: SceneElement) -> float:
    return element.bounding_box.maximum[2] - element.bounding_box.minimum[2]


class PlanStandardCameras:
    def execute(self, scene_path: Path, design_dna_path: Path | None = None) -> ViewSet:
        scene = CanonicalScene.model_validate_json(scene_path.read_text(encoding="utf-8"))
        minimum, maximum = _scene_bounds(scene)
        center = tuple((low + high) / 2 for low, high in zip(minimum, maximum, strict=True))
        span_x = maximum[0] - minimum[0]
        span_y = maximum[1] - minimum[1]
        span = max(span_x, span_y)

        architectural = _architectural_elements(scene)
        tallest = max(_height(element) for element in architectural)
        hero_candidates = [
            element for element in architectural if _height(element) >= tallest * 0.9
        ]
        hero = min(hero_candidates, key=_footprint)
        detail = max(architectural, key=_footprint)
        hero_target = _center(hero)
        detail_target = _center(detail)
        hero_width = hero.bounding_box.maximum[0] - hero.bounding_box.minimum[0]
        hero_depth = hero.bounding_box.maximum[1] - hero.bounding_box.minimum[1]
        detail_width = detail.bounding_box.maximum[0] - detail.bounding_box.minimum[0]
        detail_depth = detail.bounding_box.maximum[1] - detail.bounding_box.minimum[1]
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
                role=ViewRole.HERO,
                position=(
                    hero.bounding_box.maximum[0] + max(24.0, hero_width * 1.8),
                    hero.bounding_box.minimum[1] - max(28.0, hero_depth * 2.2),
                    hero.bounding_box.maximum[2] + max(2.0, _height(hero) * 0.2),
                ),
                target=(hero_target[0], hero_target[1], hero_target[2]),
                focal_length_mm=48,
                sensor_width_mm=36,
                aspect_ratio="16:9",
            ),
            Camera(
                view_id="view-04",
                role=ViewRole.DETAIL,
                position=(
                    detail.bounding_box.maximum[0] + max(25.0, detail_width * 0.8),
                    detail.bounding_box.minimum[1] - max(25.0, detail_depth * 0.7),
                    detail.bounding_box.maximum[2] + max(2.0, _height(detail) * 0.25),
                ),
                target=(
                    detail_target[0],
                    detail.bounding_box.minimum[1],
                    detail_target[2],
                ),
                focal_length_mm=42,
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
        if design_dna_path is not None:
            design = DesignDNA.model_validate_json(design_dna_path.read_text(encoding="utf-8"))
            design_revision = design.design_revision
        view_set = ViewSet(
            view_set_id=f"{revision_key}-{design_revision}-standard-v1",
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
