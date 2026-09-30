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
    """How much surrounding built form the provider may resolve.

    Each policy also decides how the deterministic context proxies are handled, because the two
    mechanisms are mutually exclusive: compositing a proxy over an image whose prompt asked the
    provider to build real neighbours pastes placeholder massing back over finished context, and
    sending the composition guide makes the provider draw the placeholder itself.
    """

    #: Render nothing beyond what the model authored. Empty surroundings stay empty.
    AUTHORED_ONLY = "authored_only"
    #: Photoreal ground, roads, planting and sky, but neighbouring buildings stay deterministic
    #: translucent massing composited afterwards, so context reads as context.
    TRANSLUCENT_MASSING = "translucent_massing"
    #: As above, but the provider paints the translucent massing from the camera-registered
    #: guide. Composited afterwards, massing lands where the conditioning camera saw it; when the
    #: provider moved the horizon, far volumes were pasted into the sky.
    PAINTED_MASSING = "painted_massing"
    #: Resolve authored context proxies into believable neighbouring built form.
    RESOLVE_PROXIES = "resolve_proxies"
    #: Build a plausible surrounding estate wherever the horizon is empty.
    GENERATED_SURROUNDINGS = "generated_surroundings"

    @property
    def composites_proxies(self) -> bool:
        """Whether authored context volumes are composited over the finished image."""

        return self is ContextPolicy.TRANSLUCENT_MASSING

    @property
    def sends_composition_guide(self) -> bool:
        """Whether the camera-registered proxy guide is sent to the provider.

        The provider reproduces it literally as translucent slabs, which is what painted massing
        asks for and what resolving proxies into real buildings has to overcome.
        """

        return self in {ContextPolicy.RESOLVE_PROXIES, ContextPolicy.PAINTED_MASSING}


class DesignFreedom(str, Enum):
    """How much of the architecture the provider is allowed to author.

    The system always owns what the model measures — how many buildings, where their footprints
    sit, how tall the envelope is. What varies is whether the provider may only photograph the
    authored design or may develop it. Locking everything produces a faithful photograph of a
    mediocre massing; the looser levels trade some fidelity for architecture worth showing.
    """

    #: Materials and light only. Every authored surface stays exactly as rendered.
    PHOTOREAL_ONLY = "photoreal_only"
    #: Massing, footprint and camera stay; the provider may add buildable architectural detail.
    DETAIL_WITHIN_ENVELOPE = "detail_within_envelope"
    #: Footprint, building count and height envelope stay; facade architecture is the provider's.
    DESIGN_WITHIN_ENVELOPE = "design_within_envelope"


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
    #: How much of the architecture the provider may author.
    design_freedom: DesignFreedom = DesignFreedom.PHOTOREAL_ONLY
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
