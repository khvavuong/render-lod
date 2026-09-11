from pathlib import Path

from v365_archviz.application.plan_cameras import PlanStandardCameras
from v365_archviz.domain.scene import CanonicalScene
from v365_archviz.domain.workflow import ViewRole, ViewSet


def test_plans_six_reproducible_cameras(tmp_path: Path, valid_scene: CanonicalScene) -> None:
    scene_path = tmp_path / "canonical_scene.json"
    scene_path.write_text(valid_scene.model_dump_json(), encoding="utf-8")

    first = PlanStandardCameras().execute(scene_path)
    second = PlanStandardCameras().execute(scene_path)

    assert first == second
    assert len(first.cameras) == 6
    assert len({camera.role for camera in first.cameras}) == 6
    assert {camera.role for camera in first.cameras} == {
        ViewRole.OVERALL,
        ViewRole.CONTEXT,
        ViewRole.HERO,
        ViewRole.DETAIL,
        ViewRole.OFFICE_HERO,
        ViewRole.LOADING_DETAIL,
    }
    assert first.view_set_id.endswith("standard-v21")
    close_hero = next(camera for camera in first.cameras if camera.role is ViewRole.HERO)
    human_view = next(camera for camera in first.cameras if camera.role is ViewRole.LOADING_DETAIL)
    assert close_hero.position[2] < 30
    assert human_view.position[2] == 1.65
    assert human_view.focal_length_mm == 30
    # A single-row model has no internal corridor. The human camera must stay
    # outside the architectural envelope instead of landing inside the shed.
    assert human_view.position[1] <= -34
    assert human_view.position[0] < 0
    assert human_view.target[1] >= -10
    assert ViewSet.model_validate_json((tmp_path / "view_set.json").read_text()) == first
