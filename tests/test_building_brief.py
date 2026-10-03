"""Buildings that carry a kind are named and described; a scene without kinds is left as it was."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from tests.test_design_fidelity import _plan
from tests.test_office_brief import _camera
from tests.test_studio import _upload
from v365_archviz.application.building_brief import (
    building_contract,
    building_set_rule,
    building_view_directive,
)
from v365_archviz.application.import_scene_upload import scene_upload_revision
from v365_archviz.application.refine_viewset import _identity_contract
from v365_archviz.application.refinement_prompt import compose_style_prompt
from v365_archviz.application.studio import STUDIO_STYLE_PACK
from v365_archviz.domain.design import DesignDNA
from v365_archviz.domain.scene_upload import SceneUpload
from v365_archviz.domain.style_pack import StylePack


def _with_kinds() -> dict[str, object]:
    upload = _upload()
    buildings = upload["buildings"]  # type: ignore[index]
    buildings[0].update(  # type: ignore[index]
        kind="warehouse",
        front="south",
        features={
            "roof": "gable",
            "roof_slope_deg": 5,
            "front_doors": 3,
            "end_wall_doors": 1,
            "canopy_depth_m": 2,
            "high_windows": True,
        },
    )
    buildings[1].update(kind="office_block", front="east")  # type: ignore[index]
    buildings.append(  # type: ignore[attr-defined]
        {
            "id": "guard",
            "role": "utility_block",
            "kind": "guard_house",
            "front": "south",
            "features": {"roof": "flat", "glazed_sides": 3},
            "center": [-90, -50],
            "width_m": 4,
            "length_m": 6,
            "height_m": 3.5,
        }
    )
    buildings.append(  # type: ignore[attr-defined]
        {
            "id": "pump",
            "role": "utility_block",
            "kind": "pump_house",
            "front": "north",
            "features": {"roof": "flat", "tank_lid": True},
            "center": [90, -40],
            "width_m": 6,
            "length_m": 8,
            "height_m": 4,
        }
    )
    return upload


def _design(tmp_path: Path, kinds: bool = True) -> DesignDNA:
    return _plan(tmp_path, _with_kinds() if kinds else _upload())  # type: ignore[return-value]


def test_a_scene_without_kinds_keeps_its_revision_and_its_prompt(tmp_path: Path) -> None:
    # The revision every earlier upload of this scene had: its artifacts stay reusable.
    assert scene_upload_revision(SceneUpload.model_validate(_upload())) == "30b9ddc9d7423d31"
    design = _design(tmp_path, kinds=False)
    prompt = compose_style_prompt(StylePack.load(STUDIO_STYLE_PACK), design)

    assert building_contract(design) == ""
    assert building_set_rule(design) == ""
    assert building_view_directive(design, _camera((-20.0, -260.0, 120.0))) == ""
    assert "BUILDINGS" not in prompt
    assert "buildings=" not in _identity_contract(design)[1]


def test_each_named_building_is_described_with_the_parts_the_editor_drew(
    tmp_path: Path,
) -> None:
    contract = building_contract(_design(tmp_path))

    assert contract.startswith("BUILDINGS\nBase RGB draws every building as a plain box")
    assert (
        "- The warehouse about 12 m high is a pre-engineered steel warehouse: profiled metal "
        "walls on a concrete plinth, a 5° metal gable roof with its ridge along the long side, "
        "3 grade-level steel roller shutter doors on its south side under one slim steel canopy "
        "about 2 m deep, 1 more in each end wall, a row of small high-level windows under the "
        "eaves." in contract
    )
    assert (
        "- The guard house about 3.5 m high is a single-storey guard house glazed on 3 sides"
        in (contract)
    )
    assert "the flush concrete lid of the underground water tank" in contract
    # The office keeps its own section; its look is left to the concept.
    assert "office" not in contract.lower()


def test_the_section_sits_after_the_office_and_the_set_identity_carries_it(
    tmp_path: Path,
) -> None:
    design = _design(tmp_path)
    prompt = compose_style_prompt(StylePack.load(STUDIO_STYLE_PACK), design)

    assert (
        prompt.index("\nOFFICE\n") < prompt.index("\nBUILDINGS\n") < prompt.index("ALLOWED CHANGES")
    )
    assert "buildings=each building the BUILDINGS section names" in _identity_contract(design)[1]


def test_each_view_is_told_where_each_named_building_stands(tmp_path: Path) -> None:
    # Seen from the south, the guard house (west) is on the left and the pump house (east)
    # on the right.
    directive = building_view_directive(_design(tmp_path), _camera((0.0, -260.0, 120.0)))

    assert directive.startswith("BUILDINGS IN THIS VIEW")
    assert "the guard house in the left of the frame" in directive
    assert "the pump house in the right of the frame" in directive
    assert "in front of" not in directive and "beyond" not in directive


def test_an_unknown_kind_is_refused() -> None:
    upload = _with_kinds()
    upload["buildings"][2]["kind"] = "castle"  # type: ignore[index]

    with pytest.raises(ValidationError):
        SceneUpload.model_validate(upload)


def test_buildings_of_one_kind_are_told_apart_by_size(tmp_path: Path) -> None:
    upload = _with_kinds()
    upload["buildings"].append(  # type: ignore[attr-defined]
        {
            "id": "store",
            "role": "main_shed",
            "kind": "warehouse",
            "center": [-60, 60],
            "width_m": 30,
            "length_m": 20,
            "height_m": 8,
        }
    )
    design = _plan(tmp_path, upload)
    contract = building_contract(design)  # type: ignore[arg-type]

    assert "- The larger warehouse about 12 m high" in contract
    assert "- The smaller warehouse about 8 m high" in contract
