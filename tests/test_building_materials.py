"""The wall and roof materials the editor sets are named per building and outrank the concept."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from tests.test_building_brief import _with_kinds
from tests.test_design_fidelity import _plan
from tests.test_studio import _upload
from v365_archviz.application.building_brief import building_contract, building_set_rule
from v365_archviz.application.import_scene_upload import scene_upload_revision
from v365_archviz.domain.design import DesignDNA
from v365_archviz.domain.scene_upload import SceneUpload


def _with_materials() -> dict[str, object]:
    upload = _with_kinds()
    warehouse, office, guard, pump = upload["buildings"]  # type: ignore[misc]
    warehouse.update(wall_material="concrete", roof_material="steel")
    office.update(wall_material="precast", roof_material="concrete")
    guard.update(wall_material="brick", roof_material="concrete")
    pump.update(wall_material="concrete", roof_material="concrete")
    upload["buildings"].append(  # type: ignore[attr-defined]
        {
            "id": "box",
            "role": "utility_block",
            "center": [60, -50],
            "width_m": 10,
            "length_m": 12,
            "height_m": 6,
            "wall_material": "wood",
            "roof_material": "glass",
        }
    )
    return upload


def _design(tmp_path: Path) -> DesignDNA:
    return _plan(tmp_path, _with_materials())  # type: ignore[return-value]


def test_unset_materials_keep_the_revision() -> None:
    upload = _upload()
    revision = scene_upload_revision(SceneUpload.model_validate(upload))
    for building in upload["buildings"]:  # type: ignore[union-attr]
        building.update(wall_material=None, roof_material=None)
    assert scene_upload_revision(SceneUpload.model_validate(upload)) == revision


def test_each_building_is_described_with_its_wall_and_roof_materials(tmp_path: Path) -> None:
    contract = building_contract(_design(tmp_path))

    assert (
        "- The warehouse about 12 m high is a warehouse: walls of smooth light-grey "
        "cast-in-place concrete on a concrete plinth, a 5° profiled metal gable roof with its "
        "ridge along the long side" in contract
    )
    assert "pre-engineered steel" not in contract
    assert (
        "- The guard house about 3.5 m high is a single-storey guard house with walls of "
        "fair-faced red-brown brick, glazed on 3 sides" in contract
    )
    assert (
        "a closed room with walls of smooth light-grey cast-in-place concrete under a flat "
        "concrete roof" in contract
    )
    # Buildings without a described kind are named by their role, with their materials only.
    assert (
        "- The office block about 10 m high has walls of precast concrete panels with crisp, "
        "regular joints and a concrete roof." in contract
    )
    assert (
        "- The auxiliary block about 6 m high has walls of vertical timber boarding and a glazed "
        "roof." in contract
    )
    assert "take precedence over any general material, palette or concept direction" in contract


def test_the_set_identity_keeps_the_materials(tmp_path: Path) -> None:
    assert "wall and roof materials" in building_set_rule(_design(tmp_path))


def test_an_unknown_material_is_refused() -> None:
    upload = _with_materials()
    upload["buildings"][0]["wall_material"] = "marble"  # type: ignore[index]

    with pytest.raises(ValidationError):
        SceneUpload.model_validate(upload)
