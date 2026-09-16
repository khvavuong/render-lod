"""Data-defined aesthetic direction for the generative refinement stage.

The geometry contract is owned by the system and is never negotiable. Everything above it —
how the project should look, how it should be photographed, and how much surrounding context may
be invented — is authored data so that a new design direction is a new file rather than a code
change.
"""

from __future__ import annotations

import json
from enum import Enum
from pathlib import Path

from pydantic import Field

from v365_archviz.domain.common import DomainModel


class ContextPolicy(str, Enum):
    """How much surrounding built form the provider may resolve."""

    #: Render nothing beyond what the model authored. Empty surroundings stay empty.
    AUTHORED_ONLY = "authored_only"
    #: Resolve authored context proxies into believable neighbouring built form.
    RESOLVE_PROXIES = "resolve_proxies"
    #: Build a plausible surrounding estate wherever the horizon is empty.
    GENERATED_SURROUNDINGS = "generated_surroundings"


class StylePack(DomainModel):
    """One authored aesthetic direction, layered above the immutable geometry contract."""

    schema_version: str = Field(default="1.0.0", pattern=r"^1\.0\.0$")
    pack_id: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    label: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=400)

    #: What the finished image is for. Sets the ambition of the whole pass.
    intent: str = Field(min_length=1, max_length=600)
    #: Which appearance changes the provider is invited to make.
    allowed_changes: str = Field(min_length=1, max_length=2000)
    #: Lens, light, exposure and post-processing direction.
    photography: str = Field(min_length=1, max_length=2000)
    #: How far the surroundings may be resolved.
    context_policy: ContextPolicy = ContextPolicy.RESOLVE_PROXIES
    #: Free-form note appended to the context instruction for this pack.
    context_direction: str = Field(default="", max_length=1200)
    #: Pack-specific prohibitions, added to the system-owned ones.
    prohibited: str = Field(default="", max_length=1200)

    @classmethod
    def load(cls, path: Path) -> StylePack:
        return cls.model_validate_json(path.read_text(encoding="utf-8"))

    @classmethod
    def load_catalog(cls, directory: Path) -> tuple[StylePack, ...]:
        """Load every pack in a directory, ordered by pack id."""

        packs = [cls.load(path) for path in sorted(directory.glob("*.json"))]
        identifiers = [pack.pack_id for pack in packs]
        duplicates = {value for value in identifiers if identifiers.count(value) > 1}
        if duplicates:
            raise ValueError(f"duplicate style pack ids: {', '.join(sorted(duplicates))}")
        return tuple(sorted(packs, key=lambda pack: pack.pack_id))

    def to_json(self) -> str:
        return json.dumps(self.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n"
