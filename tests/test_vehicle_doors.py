from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.test_studio import _upload
from v365_archviz import api
from v365_archviz.application.plan_design import PlanDesign
from v365_archviz.application.refinement_prompt import (
    VIETNAMESE_DOOR_RULE,
    build_refinement_prompt,
)
from v365_archviz.application.studio import STUDIO_STYLE_PACK, find_concept_presets
from v365_archviz.domain.design import DesignBrief
from v365_archviz.domain.style_pack import StylePack

client = TestClient(api.app)


def test_every_prompt_asks_for_grade_level_doors_never_truck_docks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("V365_ARTIFACT_DIR", str(tmp_path))
    revision = client.post("/v1/scenes", json=_upload()).json()["model_revision"]
    scene_path = tmp_path / "scenes" / revision / "canonical_scene.json"
    (preset,) = find_concept_presets(("industrial_park_classic",))
    brief_path = tmp_path / "brief.json"
    brief_path.write_text(
        DesignBrief.model_validate({**preset.brief, "project_id": "p"}).model_dump_json(),
        encoding="utf-8",
    )
    design = PlanDesign().execute(scene_path, brief_path)
    design_path = scene_path.parent / "designs" / design.design_revision / "design_dna.json"

    _, prompt = build_refinement_prompt(design_path, style_pack=StylePack.load(STUDIO_STYLE_PACK))

    doors = [
        door
        for building in design.buildings
        for facade in building.facades
        for door in facade.loading_docks
    ]
    assert doors
    assert {door.door_type for door in doors} == {"roller_shutter"}
    assert VIETNAMESE_DOOR_RULE in prompt
    assert "sectional" not in prompt.lower()
