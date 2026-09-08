import json
from pathlib import Path

from v365_archviz.application.plan_design import PlanDesign
from v365_archviz.domain.design import DesignDNA
from v365_archviz.domain.scene import CanonicalScene
from v365_archviz.providers.ifc import _box_surfaces


def test_plans_reproducible_design_dna(
    tmp_path: Path, valid_scene: CanonicalScene
) -> None:
    surfaces = tuple(
        surface
        for element in valid_scene.elements
        for surface in _box_surfaces(
            element.scene_element_id,
            element.bounding_box,
            element.semantic_role,
        )
    )
    scene = valid_scene.model_copy(update={"surfaces": surfaces})
    scene_path = tmp_path / "canonical_scene.json"
    scene_path.write_text(scene.model_dump_json(), encoding="utf-8")
    brief_path = tmp_path / "design_brief.json"
    brief_path.write_text(
        """{
          "project_id": "test-project",
          "design_language": {
            "style": "test style",
            "primary_material": "material a",
            "secondary_material": "material b",
            "office_material": "material c"
          },
          "environment": {
            "time": "09:30",
            "weather": "clear",
            "sun_azimuth_deg": 135,
            "sun_elevation_deg": 45,
            "white_balance_k": 5600
          },
          "panel_module_m": 1.2,
          "loading_docks_per_main_facade": 2,
          "add_office_entrances": true,
          "roof_type": "preserve source",
          "solar_panels": false,
          "grammar_version": "test-v1",
          "asset_library_version": "test-assets-v1"
        }""",
        encoding="utf-8",
    )

    first = PlanDesign().execute(scene_path, brief_path)
    second = PlanDesign().execute(scene_path, brief_path)

    assert first == second
    assert first.design_revision.startswith("R01-")
    assert len(first.buildings) == 2
    shed = next(item for item in first.buildings if item.building_id == "shed-1")
    office = next(item for item in first.buildings if item.building_id == "office-1")
    assert shed.facades[0].loading_docks
    assert office.facades[0].office_entrance is not None
    assert office.facades[0].articulation.office_glazing_ratio == 0.72
    assert first.material_palette.primary_hex == "#E7E5DF"
    design_path = tmp_path / "designs" / first.design_revision / "design_dna.json"
    assert DesignDNA.model_validate_json(
        design_path.read_text(encoding="utf-8")
    ) == first

    changed_brief = json.loads(brief_path.read_text(encoding="utf-8"))
    changed_brief["design_language"]["style"] = "a different approved project style"
    brief_path.write_text(json.dumps(changed_brief), encoding="utf-8")
    changed = PlanDesign().execute(scene_path, brief_path)
    assert changed.design_revision != first.design_revision
    assert design_path.is_file()
    assert (
        tmp_path / "designs" / changed.design_revision / "design_dna.json"
    ).is_file()
