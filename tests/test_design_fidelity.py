"""A concept may redesign the skin, never the buildings: the massing is the client's design."""

from pathlib import Path

import pytest

from tests.test_studio import _upload
from v365_archviz.application.import_scene_upload import ImportSceneUpload
from v365_archviz.application.plan_design import PlanDesign
from v365_archviz.application.studio import STUDIO_STYLE_PACK, find_concept_presets
from v365_archviz.domain.design import DesignBrief
from v365_archviz.domain.scene_upload import SceneUpload
from v365_archviz.domain.style_pack import ContextPolicy, DesignFreedom, StylePack


def _plan(tmp_path: Path, upload: dict) -> object:
    imported = ImportSceneUpload().execute(SceneUpload.model_validate(upload), tmp_path)
    (preset,) = find_concept_presets(("industrial_park_classic",))
    brief_path = tmp_path / "brief.json"
    brief_path.write_text(
        DesignBrief.model_validate({**preset.brief, "project_id": "p"}).model_dump_json(),
        encoding="utf-8",
    )
    return PlanDesign().execute(imported.scene_path, brief_path)


def test_buildings_nine_metres_apart_keep_their_own_roofs(tmp_path: Path) -> None:
    upload = _upload()
    # A second shed 9 m beside the first, as in a real project that was merged into one roof.
    upload["buildings"].append(  # type: ignore[union-attr]
        {
            "id": "shed-2",
            "role": "main_shed",
            "center": [10, 84],
            "width_m": 120,
            "length_m": 60,
            "height_m": 12,
        }
    )

    design = _plan(tmp_path, upload)

    assemblies = [set(assembly.building_ids) for assembly in design.roof_assemblies]
    assert {"shed"} in assemblies
    assert {"shed-2"} in assemblies


def test_a_model_without_an_office_gets_no_office_entrance(tmp_path: Path) -> None:
    upload = _upload()
    upload["buildings"][1]["role"] = "utility_block"  # type: ignore[index]

    design = _plan(tmp_path, upload)

    entrances = [
        facade.office_entrance
        for building in design.buildings
        for facade in building.facades
        if facade.office_entrance is not None
    ]
    assert entrances == []


def test_every_preset_keeps_its_buildings_separate_and_invents_no_surroundings() -> None:
    for preset in find_concept_presets(
        (
            "industrial_park_classic",
            "green_industrial",
            "corporate_identity",
            "tropical_climate",
            "refined_minimal",
        )
    ):
        brief = DesignBrief.model_validate({**preset.brief, "project_id": "p"})
        assert brief.roof_grouping_mode == "per_element", preset.preset_id
        assert brief.site_design.surrounding_context_mode == "authored_only", preset.preset_id


def test_the_studio_style_keeps_the_layout_and_leaves_neighbours_out() -> None:
    pack = StylePack.load(STUDIO_STYLE_PACK)

    # Roads, yards, planting and openings stay as designed; the skin is still the provider's.
    assert pack.design_freedom is DesignFreedom.DETAIL_WITHIN_ENVELOPE
    # The project is the only building: no neighbour, painted or composited, reaches the image.
    assert pack.context_policy is ContextPolicy.OPEN_ESTATE
    assert not pack.context_policy.sends_composition_guide
    assert not pack.context_policy.composites_proxies


def test_an_open_estate_asks_for_no_neighbouring_building() -> None:
    from v365_archviz.application.refinement_prompt import _CONTEXT_INSTRUCTION

    instruction = _CONTEXT_INSTRUCTION[ContextPolicy.OPEN_ESTATE]

    assert "the only building in the image" in instruction
    assert "no other building" in instruction


def test_a_project_without_neighbours_is_not_told_about_translucent_massing(
    tmp_path: Path,
) -> None:
    from v365_archviz.application.refine_viewset import _identity_contract

    _, set_prompt = _identity_contract(_plan(tmp_path, _upload()))

    assert "translucent" not in set_prompt


@pytest.fixture(autouse=True)
def _artifacts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("V365_ARTIFACT_DIR", str(tmp_path))
