"""A vehicle gate as the editor draws it, block by block.

Site Forma draws a gate as two capped pillars at the ends of the opening, a barrier
cabinet inside one pillar and a red and white striped arm to a rest post by the other.
It sends those blocks, so the conditioning render builds the gate the user placed
instead of a generic one.
"""

from __future__ import annotations

import math
from typing import Literal

from pydantic import model_validator

from v365_archviz.domain.common import DomainModel

GateRole = Literal["main", "secondary"]
GatePartKind = Literal["pillar", "cap", "cabinet", "arm_red", "arm_white", "rest"]


class GatePart(DomainModel):
    """One upright block of a gate, turned with it.

    `center` is in world metres; `size` is along the opening, across it and up;
    the opening runs along (cos, sin) of `rotation_rad`.
    """

    kind: GatePartKind
    center: tuple[float, float, float]
    size: tuple[float, float, float]
    rotation_rad: float = 0.0

    @model_validator(mode="after")
    def validate_block(self) -> GatePart:
        if not all(math.isfinite(value) for value in (*self.center, *self.size, self.rotation_rad)):
            raise ValueError("gate part values must be finite")
        if not all(0 < value <= 100 for value in self.size):
            raise ValueError("gate part sizes must be positive and at most 100 m")
        return self
