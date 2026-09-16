import math
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
    assert first.view_set_id.endswith("standard-v39")
    hero_aerial = next(camera for camera in first.cameras if camera.role is ViewRole.OVERALL)
    arrival = next(camera for camera in first.cameras if camera.role is ViewRole.CONTEXT)
    logistics = next(camera for camera in first.cameras if camera.role is ViewRole.HERO)
    reverse_aerial = next(camera for camera in first.cameras if camera.role is ViewRole.DETAIL)
    office_detail = next(camera for camera in first.cameras if camera.role is ViewRole.OFFICE_HERO)
    human_view = next(camera for camera in first.cameras if camera.role is ViewRole.LOADING_DETAIL)
    assert hero_aerial.position[2] >= 25
    assert hero_aerial.focal_length_mm == 28
    assert arrival.position[2] == 1.75
    assert 3.2 <= logistics.position[2] <= 12
    assert reverse_aerial.position[2] >= 25
    assert reverse_aerial.focal_length_mm == 28
    for aerial in (hero_aerial, reverse_aerial):
        horizontal = math.hypot(
            aerial.position[0] - aerial.target[0],
            aerial.position[1] - aerial.target[1],
        )
        depression = math.degrees(
            math.atan2(aerial.position[2] - aerial.target[2], horizontal)
        )
        assert 18 <= depression <= 45
    assert office_detail.position[2] == 1.85
    assert human_view.position[2] == 1.65
    assert human_view.focal_length_mm == 35
    # A single-row model has no internal corridor. The human camera must stay
    # outside the architectural envelope instead of landing inside the shed.
    assert human_view.position[1] <= -34
    assert 0 <= human_view.position[0] <= 60
    assert human_view.target[1] >= -10
    assert ViewSet.model_validate_json((tmp_path / "view_set.json").read_text()) == first
