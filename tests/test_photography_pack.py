import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from v365_archviz.domain.photography_pack import PhotographyPack, RoleFraming
from v365_archviz.domain.workflow import PLANNED_ROLES, ViewRole

PACK_DIRECTORY = Path("resource/photography_packs")


def _pack(**overrides: object) -> PhotographyPack:
    roles = {
        role: RoleFraming(
            elevation_deg=10.0,
            eye_height_m=1.7,
            focal_length_mm=35.0,
            target_width_coverage=0.6,
        )
        for role in ViewRole
    }
    fields: dict[str, object] = {
        "pack_id": "example_pack",
        "label": "Example",
        "description": "An example photographic approach.",
        "roles": roles,
    }
    fields.update(overrides)
    return PhotographyPack.model_validate(fields)


def test_checked_in_packs_cover_every_standard_role() -> None:
    packs = PhotographyPack.load_catalog(PACK_DIRECTORY)

    assert len(packs) >= 2
    for pack in packs:
        # A custom camera is placed by the user, never planned from a pack.
        for role in PLANNED_ROLES:
            assert pack.framing_for(role) is not None


def test_packs_author_intent_not_distances() -> None:
    """A metre stand-off tuned on one model is the failure this pack exists to remove."""

    for path in sorted(PACK_DIRECTORY.glob("*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        for role, framing in document["roles"].items():
            assert "distance" not in " ".join(framing), f"{path.name}:{role} authors a distance"
            assert set(framing) <= {
                "elevation_deg",
                "eye_height_m",
                "focal_length_mm",
                "target_width_coverage",
                "max_foreground_share",
                "roofline_margin",
            }


def test_ground_level_roles_declare_an_eye_height() -> None:
    packs = PhotographyPack.load_catalog(PACK_DIRECTORY)
    ground_roles = {ViewRole.CONTEXT, ViewRole.OFFICE_HERO, ViewRole.LOADING_DETAIL}

    for pack in packs:
        for role in ground_roles:
            assert pack.framing_for(role).eye_height_m is not None


def test_missing_role_is_rejected_rather_than_defaulted() -> None:
    pack = _pack(roles={ViewRole.OVERALL: RoleFraming(
        elevation_deg=28.0, focal_length_mm=28.0, target_width_coverage=0.8
    )})

    with pytest.raises(ValueError, match="no framing for"):
        pack.framing_for(ViewRole.CONTEXT)


def test_negative_elevation_is_rejected() -> None:
    with pytest.raises(ValidationError):
        RoleFraming(elevation_deg=-5.0, focal_length_mm=35.0, target_width_coverage=0.6)


def test_duplicate_pack_ids_are_rejected(tmp_path: Path) -> None:
    for name in ("a.json", "b.json"):
        (tmp_path / name).write_text(_pack().to_json(), encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate photography pack ids"):
        PhotographyPack.load_catalog(tmp_path)
