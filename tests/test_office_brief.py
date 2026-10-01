"""The office is named, ranked and placed, and its look is left to the concept's style."""

from pathlib import Path

import pytest

from tests.test_design_fidelity import _plan
from tests.test_studio import _upload
from v365_archviz.application.office_brief import office_contract, office_view_directive
from v365_archviz.application.refine_viewset import _identity_contract
from v365_archviz.application.refinement_prompt import compose_style_prompt
from v365_archviz.application.studio import STUDIO_STYLE_PACK
from v365_archviz.domain.design import DesignDNA
from v365_archviz.domain.style_pack import StylePack
from v365_archviz.domain.workflow import Camera, ViewRole

#: Words that would impose one office style on every concept.
PRESCRIBED_LOOK = ("curtain wall", "louvre", "fins", "canopy", "glazing", "double-height")


def _design(tmp_path: Path, office: bool = True) -> DesignDNA:
    upload = _upload()
    buildings = upload["buildings"]  # type: ignore[index]
    buildings[1]["floors"] = 3  # type: ignore[index]
    if not office:
        buildings[1]["role"] = "utility_block"  # type: ignore[index]
    return _plan(tmp_path, upload)  # type: ignore[return-value]


def _camera(position: tuple[float, float, float]) -> Camera:
    return Camera(
        view_id="view-01",
        role=ViewRole.OVERALL,
        position=position,
        target=(-20.0, -10.0, 0.0),
        focal_length_mm=35.0,
        sensor_width_mm=36.0,
        aspect_ratio="16:9",
    )


def test_the_office_is_named_by_its_storeys_size_and_rank(tmp_path: Path) -> None:
    contract = office_contract(_design(tmp_path))

    assert contract.startswith("OFFICE\nThe office is the 3-storey block about 10 m high")
    assert "the smallest of the 3 buildings" in contract
    assert "reads as 3 floor levels" in contract


def test_the_office_gets_hierarchy_and_coherence_but_no_prescribed_look(tmp_path: Path) -> None:
    contract = office_contract(_design(tmp_path)).lower()

    assert "the most design intent of the project" in contract
    assert "one project by one architect" in contract
    assert "never a different style" in contract
    assert "derive it from this concept's own style direction" in contract
    assert not [word for word in PRESCRIBED_LOOK if word in contract]
    # The emphasis is designed, not framed: the camera stays where Base RGB put it.
    assert "not a camera brief" in contract


def test_a_model_without_an_office_gets_no_office_section(tmp_path: Path) -> None:
    design = _design(tmp_path, office=False)
    pack = StylePack.load(STUDIO_STYLE_PACK)

    assert office_contract(design) == ""
    assert "\nOFFICE\n" not in compose_style_prompt(pack, design)
    assert "office=" not in _identity_contract(design)[1]


def test_the_concept_prompt_and_the_set_identity_carry_the_office(tmp_path: Path) -> None:
    design = _design(tmp_path)
    prompt = compose_style_prompt(StylePack.load(STUDIO_STYLE_PACK), design)

    assert "\nOFFICE\nThe office is" in prompt
    assert prompt.index("MASSING") < prompt.index("\nOFFICE\n") < prompt.index("ALLOWED CHANGES")
    assert "oversized glass showroom" not in prompt
    assert "office=the office keeps exactly the design" in _identity_contract(design)[1]


@pytest.mark.parametrize(
    ("position", "expected"),
    [
        # The office stands south-west of the shed: on the left seen from the south.
        ((-20.0, -260.0, 120.0), "the office stands in the left of the frame, at the size"),
        # And on the right seen from the north.
        ((-20.0, 140.0, 80.0), "the office stands in the right of the frame, at the size"),
    ],
)
def test_each_view_is_told_where_the_office_stands(
    tmp_path: Path, position: tuple[float, float, float], expected: str
) -> None:
    directive = office_view_directive(_design(tmp_path), _camera(position))

    assert expected in directive
    # Depth relations read as placement instructions and moved the office.
    assert "in front of" not in directive and "beyond" not in directive


def test_a_view_that_cannot_see_the_office_gives_its_design_to_no_one(tmp_path: Path) -> None:
    camera = Camera(
        view_id="view-02",
        role=ViewRole.DETAIL,
        position=(200.0, 10.0, 20.0),
        target=(400.0, 10.0, 0.0),
        focal_length_mm=35.0,
        sensor_width_mm=36.0,
        aspect_ratio="16:9",
    )

    directive = office_view_directive(_design(tmp_path), camera)

    assert "outside this frame" in directive
    assert office_view_directive(_design(tmp_path / "plain", office=False), camera) == ""


@pytest.fixture(autouse=True)
def _artifacts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("V365_ARTIFACT_DIR", str(tmp_path))
