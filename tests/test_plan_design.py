import json
from pathlib import Path

from v365_archviz.application.plan_design import PlanDesign, _roof_groups
from v365_archviz.domain.design import BuildingTreatment, DesignDNA
from v365_archviz.domain.scene import BoundingBox, CanonicalScene, SemanticRole
from v365_archviz.providers.ifc import _box_surfaces


def test_plans_reproducible_design_dna(tmp_path: Path, valid_scene: CanonicalScene) -> None:
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
          "design_preferences": {
            "style_preset": "sustainable_industrial",
            "decor_level": "subtle",
            "requested_office_storeys": 3,
            "creative_prompt": "A calm, climate-responsive arrival facade."
          },
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
    assert len(first.roof_assemblies) == 1
    shed = next(item for item in first.buildings if item.building_id == "shed-1")
    office = next(item for item in first.buildings if item.building_id == "office-1")
    assert sum(bool(facade.loading_docks) for facade in shed.facades) == 1
    assert sum(facade.office_entrance is not None for facade in office.facades) == 1
    assert office.facades[0].articulation.office_glazing_ratio == 0.72
    assert first.material_palette.primary_hex == "#E7E5DF"
    assert first.design_preferences.style_preset.value == "sustainable_industrial"
    assert first.design_preferences.requested_office_storeys == 3
    assert first.design_preferences.creative_prompt == (
        "A calm, climate-responsive arrival facade."
    )
    design_path = tmp_path / "designs" / first.design_revision / "design_dna.json"
    assert DesignDNA.model_validate_json(design_path.read_text(encoding="utf-8")) == first

    changed_brief = json.loads(brief_path.read_text(encoding="utf-8"))
    changed_brief["design_language"]["style"] = "a different approved project style"
    brief_path.write_text(json.dumps(changed_brief), encoding="utf-8")
    changed = PlanDesign().execute(scene_path, brief_path)
    assert changed.design_revision != first.design_revision
    assert design_path.is_file()
    assert (tmp_path / "designs" / changed.design_revision / "design_dna.json").is_file()


def test_groups_aligned_lod_blocks_into_two_continuous_roofs(
    valid_scene: CanonicalScene,
) -> None:
    source = valid_scene.elements[0]
    boxes = (
        BoundingBox(minimum=(0, 0, 0), maximum=(40, 60, 11)),
        BoundingBox(minimum=(40, 0, 0), maximum=(80, 60, 11)),
        BoundingBox(minimum=(0, 100, 0), maximum=(40, 160, 11)),
        BoundingBox(minimum=(47, 100, 0), maximum=(87, 160, 11)),
    )
    sheds = [
        source.model_copy(
            update={"scene_element_id": f"shed-{index}", "bounding_box": bounding_box}
        )
        for index, bounding_box in enumerate(boxes, start=1)
    ]

    groups = _roof_groups(sheds, "continuous_rows", gap_tolerance=10.0)

    assert len(groups) == 2
    assert sorted(len(group) for group in groups) == [2, 2]


def test_explicit_focus_scope_turns_other_buildings_into_context(
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
    scene_path = tmp_path / "canonical_scene.json"
    scene_path.write_text(
        valid_scene.model_copy(update={"surfaces": surfaces}).model_dump_json(),
        encoding="utf-8",
    )
    brief = {
        "project_id": "project",
        "design_language": {
            "style": "restrained industrial",
            "primary_material": "metal cladding",
            "secondary_material": "dark metal",
            "office_material": "shaded glazing",
        },
        "environment": {
            "time": "09:30",
            "weather": "clear",
            "sun_azimuth_deg": 135,
            "sun_elevation_deg": 45,
            "white_balance_k": 5600,
        },
        "panel_module_m": 1.2,
        "roof_type": "low-slope gable roof",
        "focus_building_ids": ["shed-1"],
        "grammar_version": "test",
        "asset_library_version": "test",
    }
    brief_path = tmp_path / "brief.json"
    brief_path.write_text(json.dumps(brief), encoding="utf-8")

    design = PlanDesign().execute(scene_path, brief_path)

    shed = next(item for item in design.buildings if item.building_id == "shed-1")
    office = next(item for item in design.buildings if item.building_id == "office-1")
    assert shed.treatment is BuildingTreatment.FOCUS
    assert len(shed.facades) == 4
    assert office.treatment is BuildingTreatment.CONTEXT
    assert office.facades == ()


def test_places_operational_openings_on_one_courtyard_facade(
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
    brief_path = tmp_path / "brief.json"
    brief_path.write_text(
        """{
          "project_id": "test-project",
          "design_language": {
            "style": "restrained industrial", "primary_material": "metal",
            "secondary_material": "metal", "office_material": "glass"
          },
          "environment": {
            "time": "09:30", "weather": "clear", "sun_azimuth_deg": 135,
            "sun_elevation_deg": 45, "white_balance_k": 5600
          },
          "panel_module_m": 1.2, "loading_docks_per_main_facade": 2,
          "add_office_entrances": true, "roof_type": "gable",
          "grammar_version": "v1", "asset_library_version": "v1"
        }""",
        encoding="utf-8",
    )

    design = PlanDesign().execute(scene_path, brief_path)
    shed = next(item for item in design.buildings if item.building_id == "shed-1")
    office = next(item for item in design.buildings if item.building_id == "office-1")

    assert sum(bool(facade.loading_docks) for facade in shed.facades) == 1
    assert sum(facade.office_entrance is not None for facade in office.facades) == 1


def test_default_scope_keeps_utility_blocks_opaque_and_undecorated(
    tmp_path: Path, valid_scene: CanonicalScene
) -> None:
    utility = valid_scene.elements[0].model_copy(
        update={
            "scene_element_id": "utility-1",
            "mesh_ref": "meshes/utility.npz",
            "bounding_box": BoundingBox(minimum=(65, 0, 0), maximum=(77, 6, 4)),
            "semantic_role": SemanticRole.UTILITY_BLOCK,
        }
    )
    scene = valid_scene.model_copy(update={"elements": (*valid_scene.elements, utility)})
    surfaces = tuple(
        surface
        for element in scene.elements
        for surface in _box_surfaces(
            element.scene_element_id, element.bounding_box, element.semantic_role
        )
    )
    scene_path = tmp_path / "canonical_scene.json"
    scene_path.write_text(scene.model_copy(update={"surfaces": surfaces}).model_dump_json())
    brief_path = tmp_path / "brief.json"
    brief_path.write_text(
        """{
          "project_id":"project",
          "design_language":{"style":"industrial","primary_material":"metal",
            "secondary_material":"metal","office_material":"glass"},
          "environment":{"time":"09:30","weather":"clear","sun_azimuth_deg":135,
            "sun_elevation_deg":45,"white_balance_k":5600},
          "panel_module_m":1.2,
          "roof_type":"low-slope gable roof","grammar_version":"v1",
          "asset_library_version":"v1"
        }"""
    )

    design = PlanDesign().execute(scene_path, brief_path)
    auxiliary = next(item for item in design.buildings if item.building_id == "utility-1")

    assert auxiliary.treatment is BuildingTreatment.AUXILIARY
    assert auxiliary.facades == ()
