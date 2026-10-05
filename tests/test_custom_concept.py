from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.test_studio import _upload
from v365_archviz import api
from v365_archviz.application.custom_concept import (
    CUSTOM_CONCEPT_NAME,
    adjusted_preset,
    prompt_preset,
)
from v365_archviz.application.plan_design import PlanDesign
from v365_archviz.application.refine_viewset import _identity_contract
from v365_archviz.application.refinement_prompt import build_refinement_prompt
from v365_archviz.application.studio import find_concept_presets
from v365_archviz.domain.design import DesignBrief
from v365_archviz.errors import InvalidModelError
from v365_archviz.providers.local_jobs import LocalJobRepository

client = TestClient(api.app)

PROMPT = (
    "Tường đỏ đô sang trọng, khung than chì và rất nhiều cây nhiệt đới. "
    "Thêm một cổng mới phía đông."
)


def test_a_description_becomes_a_preset_without_its_geometry_requests() -> None:
    preset = prompt_preset(PROMPT)

    assert preset.preset_id == prompt_preset(PROMPT).preset_id
    assert preset.preset_id.startswith("custom-")
    assert preset.name == CUSTOM_CONCEPT_NAME
    kept = "Tường đỏ đô sang trọng, khung than chì và rất nhiều cây nhiệt đới."
    assert preset.summary == kept
    brief = DesignBrief.model_validate({**preset.brief, "project_id": "p"})
    assert brief.design_preferences.client_prompt == kept


def test_a_description_with_nothing_to_design_is_refused() -> None:
    with pytest.raises(InvalidModelError):
        prompt_preset("Remove the roof.")


def test_the_description_replaces_the_preset_look_in_every_prompt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("V365_ARTIFACT_DIR", str(tmp_path))
    revision = client.post("/v1/scenes", json=_upload()).json()["model_revision"]
    scene_path = tmp_path / "scenes" / revision / "canonical_scene.json"
    brief_path = tmp_path / "brief.json"
    brief = DesignBrief.model_validate({**prompt_preset(PROMPT).brief, "project_id": "p"})
    brief_path.write_text(brief.model_dump_json(), encoding="utf-8")
    design = PlanDesign().execute(scene_path, brief_path)
    design_path = scene_path.parent / "designs" / design.design_revision / "design_dna.json"

    _, concept_prompt = build_refinement_prompt(design_path)
    _, set_prompt = _identity_contract(design)

    assert "Client description" in concept_prompt
    assert "Tường đỏ đô" in concept_prompt
    assert design.material_palette.primary_hex not in concept_prompt
    assert "Tường đỏ đô" in set_prompt
    assert design.material_palette.primary_hex not in set_prompt


def test_a_description_starts_one_concept(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("V365_ARTIFACT_DIR", str(tmp_path))
    revision = client.post("/v1/scenes", json=_upload()).json()["model_revision"]

    response = client.post(
        "/v1/studio/concepts",
        json={"model_revision": revision, "project_id": "project-1", "prompt": PROMPT},
    )
    refused = client.post(
        "/v1/studio/concepts",
        json={"model_revision": revision, "project_id": "project-1", "prompt": "Remove the roof."},
    )

    assert response.status_code == 202
    (concept,) = response.json()["concepts"]
    assert concept["name"] == CUSTOM_CONCEPT_NAME
    assert concept["preset_id"].startswith("custom-")
    job = LocalJobRepository(tmp_path / "metadata").get_by_view_set(concept["view_set_id"])
    assert job.design_revision == concept["design_revision"]
    assert refused.status_code == 422


def test_an_adjustment_is_its_own_design_and_reaches_the_prompt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("V365_ARTIFACT_DIR", str(tmp_path))
    revision = client.post("/v1/scenes", json=_upload()).json()["model_revision"]
    scene_path = tmp_path / "scenes" / revision / "canonical_scene.json"
    (preset,) = find_concept_presets(("industrial_park_classic",))

    adjusted = adjusted_preset(preset, "Darker roof and more planting at the entrance.")
    again = adjusted_preset(preset, "Darker roof and more planting at the entrance.")
    brief_path = tmp_path / "brief.json"
    brief = DesignBrief.model_validate({**adjusted.brief, "project_id": "p"})
    brief_path.write_text(brief.model_dump_json(), encoding="utf-8")
    design = PlanDesign().execute(scene_path, brief_path)
    design_path = scene_path.parent / "designs" / design.design_revision / "design_dna.json"
    _, prompt = build_refinement_prompt(design_path)

    assert adjusted.preset_id.startswith("industrial_park_classic-adj-")
    assert adjusted.preset_id == again.preset_id
    assert adjusted.name == preset.name
    assert "Client adjustment to apply to this concept: Darker roof" in prompt
    with pytest.raises(InvalidModelError):
        adjusted_preset(preset, "Remove the roof.")


def test_an_adjustment_starts_one_concept_from_one_direction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("V365_ARTIFACT_DIR", str(tmp_path))
    revision = client.post("/v1/scenes", json=_upload()).json()["model_revision"]
    body = {"model_revision": revision, "project_id": "project-1"}

    adjusted = client.post(
        "/v1/studio/concepts",
        json={**body, "preset_ids": ["green_industrial"], "adjustment": "Warmer facade colours."},
    )
    described = client.post(
        "/v1/studio/concepts",
        json={**body, "prompt": PROMPT, "adjustment": "Warmer facade colours."},
    )
    ambiguous = client.post(
        "/v1/studio/concepts", json={**body, "adjustment": "Warmer facade colours."}
    )

    assert adjusted.status_code == 202
    (concept,) = adjusted.json()["concepts"]
    assert concept["preset_id"].startswith("green_industrial-adj-")
    assert described.json()["concepts"][0]["preset_id"].startswith("custom-")
    assert ambiguous.status_code == 422
