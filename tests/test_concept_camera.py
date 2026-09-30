import math
from pathlib import Path

import pytest

from tests.test_studio import _upload
from v365_archviz.application import studio
from v365_archviz.application.import_scene_upload import ImportSceneUpload

# Imported before the autouse fixture stubs it for the rest of the suite.
from v365_archviz.application.studio import (
    StartConcepts,
    find_concept_presets,
    first_accepted_camera,
)
from v365_archviz.application.validate_conditioning import ConditioningValidationArtifacts
from v365_archviz.config import Settings
from v365_archviz.domain.scene_upload import SceneUpload
from v365_archviz.domain.workflow import Camera, ViewRole, ViewSet


def _camera(x: float) -> Camera:
    return Camera(
        view_id="view-01",
        role=ViewRole.OVERALL,
        position=(x, -200.0, 90.0),
        target=(0.0, 0.0, 2.0),
        focal_length_mm=28,
        sensor_width_mm=36,
        aspect_ratio="16:9",
    )


def _bearing(camera: Camera) -> float:
    return math.degrees(
        math.atan2(camera.position[1] - camera.target[1], camera.position[0] - camera.target[0])
    )


def test_a_refused_concept_camera_is_replaced_once_per_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("V365_ARTIFACT_DIR", str(tmp_path))
    settings = Settings.from_env()
    imported = ImportSceneUpload().execute(SceneUpload.model_validate(_upload()), tmp_path)
    (preset,) = find_concept_presets(("refined_minimal",))
    design_path = StartConcepts._plan_design(
        settings, imported.scene, imported.scene_path, imported.model_revision, preset, "p"
    )
    checks: list[tuple[Camera, ...]] = []

    def accept_second_fallback(*args: object) -> Camera:
        candidates = args[-1]
        assert isinstance(candidates, tuple)
        checks.append(candidates)
        return candidates[2]

    monkeypatch.setattr(studio, "first_accepted_camera", accept_second_fallback)

    hero = studio.studio_hero(
        settings, imported.scene, imported.scene_path, imported.model_revision, design_path
    )
    again = studio.studio_hero(
        settings, imported.scene, imported.scene_path, imported.model_revision, design_path
    )

    assert len(checks) == 1
    planned, *fallbacks = checks[0]
    assert len(fallbacks) == len(studio.HERO_FALLBACKS)
    assert hero == again == fallbacks[1]
    # The second fallback looks from the side opposite the first: 270 degrees round.
    assert (_bearing(hero) - _bearing(planned)) % 360 == pytest.approx(270)


class _Renderer:
    def __init__(self) -> None:
        self.batches: list[int] = []

    def execute(
        self, _scene: Path, _design: Path, view_set_path: Path, *_args: object, **_kwargs: object
    ) -> None:
        self.batches.append(len(ViewSet.model_validate_json(view_set_path.read_text()).cameras))


def _check_refusing(refused: dict[str, tuple[str, ...]]) -> type:
    class _Check:
        def execute(
            self, _scene: Path, view_set_path: Path, render_root: Path
        ) -> ConditioningValidationArtifacts:
            failed = refused[render_root.name]
            return ConditioningValidationArtifacts(view_set_path, not failed, failed)

    return _Check


ALL_FALLBACKS = ("view-01", "view-02", "view-03")


@pytest.mark.parametrize(
    ("refused", "expected", "batches"),
    [
        # The planned camera passes: nothing else is rendered.
        ({"batch-1": ()}, 0, [1]),
        # It fails: the three fallbacks share one render and the first accepted one wins.
        ({"batch-1": ("view-01",), "batch-2": ("view-01",)}, 2, [1, 3]),
        # Nothing passes: the caller keeps the planned camera.
        ({"batch-1": ("view-01",), "batch-2": ALL_FALLBACKS}, None, [1, 3]),
    ],
)
def test_the_planned_camera_is_checked_alone_before_the_fallbacks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    refused: dict[str, tuple[str, ...]],
    expected: int | None,
    batches: list[int],
) -> None:
    renderer = _Renderer()
    monkeypatch.setattr(studio, "create_conditioning_renderer", lambda _backend: renderer)
    monkeypatch.setattr(studio, "ValidateConditioningViewSet", _check_refusing(refused))
    candidates = tuple(_camera(x) for x in (0.0, 50.0, 100.0, 150.0))

    chosen = first_accepted_camera(
        Settings.from_env(), tmp_path / "scene.json", tmp_path / "dna.json", tmp_path, candidates
    )

    assert chosen == (None if expected is None else candidates[expected])
    assert renderer.batches == batches
