from pathlib import Path

from v365_archviz.application.plan_cameras import PlanStandardCameras
from v365_archviz.domain.scene import CanonicalScene
from v365_archviz.domain.workflow import ViewRole, ViewSet


def test_plans_four_reproducible_cameras(tmp_path: Path, valid_scene: CanonicalScene) -> None:
    scene_path = tmp_path / "canonical_scene.json"
    scene_path.write_text(valid_scene.model_dump_json(), encoding="utf-8")

    first = PlanStandardCameras().execute(scene_path)
    second = PlanStandardCameras().execute(scene_path)

    assert first == second
    assert len(first.cameras) == 4
    assert len({camera.role for camera in first.cameras}) == 4
    assert {camera.role for camera in first.cameras} == {
        ViewRole.OVERALL,
        ViewRole.CONTEXT,
        ViewRole.HERO,
        ViewRole.DETAIL,
    }
    assert ViewSet.model_validate_json((tmp_path / "view_set.json").read_text()) == first
