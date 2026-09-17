"""The freedom axis decides how much of the architecture the provider may author.

These lock the two properties that matter: what the system owns is stated at every level, and
what the system does not own stops being restated as a prohibition once the pack frees it.
"""

import pytest

from v365_archviz.application.refinement_prompt import (
    GEOMETRY_CONTRACT,
    geometry_contract,
)
from v365_archviz.domain.style_pack import DesignFreedom


@pytest.mark.parametrize("freedom", list(DesignFreedom))
def test_every_level_keeps_the_camera_locked(freedom: DesignFreedom) -> None:
    """Framing is the one thing no level negotiates: the gates measure against that frame."""

    assert "No camera movement, reframing, zoom or crop" in geometry_contract(freedom)


@pytest.mark.parametrize("freedom", list(DesignFreedom))
def test_every_level_keeps_landscape_planted(freedom: DesignFreedom) -> None:
    assert "must read as" in geometry_contract(freedom)
    assert "living planting" in geometry_contract(freedom)


@pytest.mark.parametrize("freedom", list(DesignFreedom))
def test_every_level_scopes_authority_to_the_project(freedom: DesignFreedom) -> None:
    """Placeholder context must never be preserved as a finished surface at any level."""

    assert "placeholder slab as a finished surface" in geometry_contract(freedom)


def test_the_strictest_level_is_the_contract_the_system_shipped_with() -> None:
    assert geometry_contract(DesignFreedom.PHOTOREAL_ONLY) == GEOMETRY_CONTRACT


def test_only_the_strictest_level_forbids_signage() -> None:
    """The reference marketing photography we are chasing carries building identity signage.

    Forbidding it everywhere was a self-inflicted limit on the marketing packs, so the ban now
    belongs to the level that also forbids every other facade change.
    """

    assert "watermarks or signage" in geometry_contract(DesignFreedom.PHOTOREAL_ONLY)
    for freedom in (
        DesignFreedom.DETAIL_WITHIN_ENVELOPE,
        DesignFreedom.DESIGN_WITHIN_ENVELOPE,
    ):
        contract = geometry_contract(freedom)
        assert "watermarks or signage" not in contract
        assert "No real brand" in contract


def test_only_the_strictest_level_calls_the_authored_facade_final() -> None:
    assert "Geometry is not negotiable" in geometry_contract(DesignFreedom.PHOTOREAL_ONLY)
    assert "yours to design" in geometry_contract(DesignFreedom.DESIGN_WITHIN_ENVELOPE)


def test_the_freest_level_still_holds_the_silhouette_and_the_docks() -> None:
    """Freedom is bounded by exactly what the downstream gates can measure."""

    contract = geometry_contract(DesignFreedom.DESIGN_WITHIN_ENVELOPE)
    assert "outline the building cuts against the sky must" in contract
    assert "vehicular opening" in contract
    assert "number of separate buildings" in contract


def test_the_boundary_clause_never_asserts_a_fence_the_scene_does_not_have() -> None:
    """Measured on both reference models, `site_boundary` covers 0.00000 of every base render:
    neither LOD100 model carries boundary geometry at all. The clause used to say "preserve every
    visible run and opening", which states a fact about the scene that is not true and leaves the
    provider to invent a fence in some views and not others. Board B lost its gate in VIEW-06
    exactly this way while VIEW-02 kept one.
    """

    from pathlib import Path

    from v365_archviz.application.refinement_prompt import build_refinement_prompt

    dna = Path(".artifacts/scenes/a7d22ba36b4fa342/designs/R01-30c3e1709447/design_dna.json")
    if not dna.is_file():
        pytest.skip("reference design DNA is not present in this checkout")
    _, prompt = build_refinement_prompt(dna)

    assert "Preserve every visible run and\nopening" not in prompt
    assert "Whatever boundary wall, fence" in prompt
    # The missing case has to carry a deterministic instruction, or consistency is left to chance.
    assert "the same perimeter and the same gate" in prompt
