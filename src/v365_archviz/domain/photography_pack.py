"""Data-defined photographic intent for camera planning.

Distances must never be authored here. A metre value tuned against one model is wrong for the
next one, which is exactly the failure this pack exists to remove. What belongs here is the
intent a photographer would state regardless of the building: how high the camera stands, how far
it looks down, what share of the frame the subject should hold. The planner solves the distance
that delivers that intent for whatever bounds the model actually has.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import Field

from v365_archviz.domain.common import DomainModel
from v365_archviz.domain.workflow import ViewRole


class RoleFraming(DomainModel):
    """Photographic intent for one camera role, independent of any model's dimensions."""

    #: Degrees above the ground plane. Negative is not permitted: cameras look down or level.
    elevation_deg: float = Field(ge=0.0, le=80.0)
    #: Camera height for ground-level roles. Aerial roles derive height from the elevation angle.
    eye_height_m: float | None = Field(default=None, ge=0.5, le=3.0)
    focal_length_mm: float = Field(gt=8.0, le=200.0)
    #: Share of the frame width the subject should span. The planner treats it as a preference
    #: that the roofline constraint may override.
    target_width_coverage: float = Field(gt=0.05, le=1.2)
    #: Largest share of the frame height allowed below the horizon, for ground-level roles.
    max_foreground_share: float = Field(default=0.35, gt=0.0, lt=1.0)
    #: Keeps the roofline inside the frame edge rather than exactly on it.
    roofline_margin: float = Field(default=0.85, gt=0.0, le=1.0)


class PhotographyPack(DomainModel):
    """One authored photographic approach covering every standard camera role."""

    schema_version: str = Field(default="1.0.0", pattern=r"^1\.0\.0$")
    pack_id: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    label: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=400)
    roles: dict[ViewRole, RoleFraming]

    def framing_for(self, role: ViewRole) -> RoleFraming:
        try:
            return self.roles[role]
        except KeyError as exc:
            raise ValueError(f"photography pack {self.pack_id} has no framing for {role}") from exc

    @classmethod
    def load(cls, path: Path) -> PhotographyPack:
        return cls.model_validate_json(path.read_text(encoding="utf-8"))

    @classmethod
    def load_catalog(cls, directory: Path) -> tuple[PhotographyPack, ...]:
        packs = [cls.load(path) for path in sorted(directory.glob("*.json"))]
        identifiers = [pack.pack_id for pack in packs]
        duplicates = {value for value in identifiers if identifiers.count(value) > 1}
        if duplicates:
            raise ValueError(f"duplicate photography pack ids: {', '.join(sorted(duplicates))}")
        return tuple(sorted(packs, key=lambda pack: pack.pack_id))

    def to_json(self) -> str:
        return json.dumps(self.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n"
