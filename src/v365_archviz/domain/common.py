"""Common immutable value objects."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

UnitInterval = Annotated[float, Field(ge=0.0, le=1.0)]
PositiveMeters = Annotated[float, Field(gt=0.0)]
Vec3 = tuple[float, float, float]
Matrix4x4 = tuple[
    tuple[float, float, float, float],
    tuple[float, float, float, float],
    tuple[float, float, float, float],
    tuple[float, float, float, float],
]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class DomainModel(BaseModel):
    """Strict base class for durable, versioned domain contracts."""

    model_config = ConfigDict(extra="forbid", frozen=True, validate_assignment=True)
