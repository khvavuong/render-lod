"""Typed, narrow-scope contracts for optional appearance references."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ReferenceRole(str, Enum):
    FACTORY_DESIGN = "factory_design_reference"
    CONTEXT_REALISM = "context_realism_reference"
    CONSTRUCTION_MATERIAL = "construction_material_reference"


@dataclass(frozen=True, slots=True)
class ReferenceCompatibility:
    compatible: bool
    findings: tuple[str, ...]


def evaluate_reference_compatibility(
    width: int,
    height: int,
    role: ReferenceRole,
) -> ReferenceCompatibility:
    """Reject images that cannot safely act as narrow photographic references.

    Semantic compatibility still requires the uploader's explicit role. This gate only
    accepts presentation-grade, landscape photography and prevents thumbnails, portrait
    crops and panoramas from becoming an accidental composition authority.
    """

    findings: list[str] = []
    if width < 768 or height < 432:
        findings.append("reference_resolution_too_low")
    aspect_ratio = width / max(1, height)
    if not 1.30 <= aspect_ratio <= 2.20:
        findings.append("reference_aspect_ratio_not_architectural_landscape")
    if role is ReferenceRole.FACTORY_DESIGN and width < height:
        findings.append("facade_reference_must_be_landscape")
    return ReferenceCompatibility(not findings, tuple(findings))
