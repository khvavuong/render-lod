from pathlib import Path

import pytest
from pydantic import ValidationError

from v365_archviz.application.refinement_prompt import (
    GEOMETRY_CONTRACT,
    compose_style_prompt,
)
from v365_archviz.domain.style_pack import ContextPolicy, StylePack

PACK_DIRECTORY = Path("resource/style_packs")


def _pack(**overrides: object) -> StylePack:
    fields: dict[str, object] = {
        "pack_id": "example_pack",
        "label": "Example",
        "description": "An example direction.",
        "intent": "Finish the render into a photograph.",
        "allowed_changes": "Resolve materials and light.",
        "photography": "Full-frame architectural photography.",
    }
    fields.update(overrides)
    return StylePack.model_validate(fields)


def test_checked_in_style_packs_load_and_offer_distinct_directions() -> None:
    packs = StylePack.load_catalog(PACK_DIRECTORY)

    assert len(packs) >= 3
    assert len({pack.pack_id for pack in packs}) == len(packs)
    # A design system must be able to express more than one look, so the shipped catalog has to
    # differ in the layers that actually drive appearance.
    assert len({pack.photography for pack in packs}) == len(packs)
    assert len({pack.context_policy for pack in packs}) > 1


def test_style_prompt_always_carries_the_system_owned_geometry_contract() -> None:
    for policy in ContextPolicy:
        prompt = compose_style_prompt(_pack(context_policy=policy))
        assert GEOMETRY_CONTRACT in prompt


def test_context_policy_selects_different_context_instructions() -> None:
    authored = compose_style_prompt(_pack(context_policy=ContextPolicy.AUTHORED_ONLY))
    generated = compose_style_prompt(_pack(context_policy=ContextPolicy.GENERATED_SURROUNDINGS))

    assert "Do not add neighbouring buildings" in authored
    assert "surrounding estate" in generated
    assert authored != generated


def test_pack_direction_and_limits_reach_the_prompt() -> None:
    prompt = compose_style_prompt(
        _pack(context_direction="Keep the horizon quiet.", prohibited="No night scene.")
    )

    assert "Keep the horizon quiet." in prompt
    assert "No night scene." in prompt


def test_pack_id_must_be_a_stable_slug() -> None:
    with pytest.raises(ValidationError):
        _pack(pack_id="Not A Slug")


def test_duplicate_pack_ids_are_rejected(tmp_path: Path) -> None:
    for name in ("a.json", "b.json"):
        (tmp_path / name).write_text(_pack().to_json(), encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate style pack ids"):
        StylePack.load_catalog(tmp_path)


def test_massing_contract_states_the_authored_volume_count(tmp_path: Path) -> None:
    """The count has to be a hard number: the edge screen cannot see an invented volume."""

    from v365_archviz.application.refinement_prompt import massing_contract

    class _Design:
        roof_assemblies = (object(), object())

    contract = massing_contract(_Design())  # type: ignore[arg-type]

    assert "exactly 2 roofed building volumes" in contract
    assert "Do not add" in contract
    assert "stay open" in contract
