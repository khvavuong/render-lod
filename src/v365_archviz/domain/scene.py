"""Canonical geometry contracts independent of Autodesk transport formats."""

from __future__ import annotations

import math
from enum import Enum

from pydantic import Field, model_validator

from v365_archviz.domain.common import DomainModel, Matrix4x4, PositiveMeters, Vec3


class GeometryProviderKind(str, Enum):
    AEC_DATA_MODEL = "aec_data_model"
    MODEL_DERIVATIVE = "model_derivative"
    REVIT_AUTOMATION = "revit_automation"
    LOCAL_FIXTURE = "local_fixture"


class ConstraintLevel(str, Enum):
    HARD = "hard"
    SOFT = "soft"


class SemanticRole(str, Enum):
    UNKNOWN = "unknown"
    MAIN_SHED = "main_shed"
    OFFICE_BLOCK = "office_block"
    LOADING_ZONE = "loading_zone"
    SERVICE_YARD = "service_yard"
    UTILITY_BLOCK = "utility_block"
    PARKING = "parking"
    MAIN_ENTRANCE = "main_entrance"
    SECONDARY_ENTRANCE = "secondary_entrance"
    LANDSCAPE_ZONE = "landscape_zone"
    ROOF = "roof"
    SITE_BOUNDARY = "site_boundary"
    PRIMARY_FACADE = "primary_facade"


class SourceModelRef(DomainModel):
    provider: GeometryProviderKind
    project_id: str = Field(min_length=1)
    model_id: str = Field(min_length=1)
    version_id: str = Field(min_length=1)
    source_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


class SourceElementRef(DomainModel):
    external_id: str = Field(min_length=1)
    category: str | None = None
    type_name: str | None = None


class CoordinateSystem(DomainModel):
    linear_unit: str = "meter"
    up_axis: str = "Z"
    handedness: str = "right"
    source_to_world: Matrix4x4


class BoundingBox(DomainModel):
    minimum: Vec3
    maximum: Vec3

    @model_validator(mode="after")
    def validate_extent(self) -> BoundingBox:
        if any(low > high for low, high in zip(self.minimum, self.maximum, strict=True)):
            raise ValueError("bounding box minimum must not exceed maximum")
        return self


class SceneElement(DomainModel):
    scene_element_id: str = Field(min_length=1)
    source: SourceElementRef
    transform: Matrix4x4
    mesh_ref: str = Field(min_length=1)
    bounding_box: BoundingBox
    semantic_role: SemanticRole = SemanticRole.UNKNOWN
    semantic_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    constraint_level: ConstraintLevel = ConstraintLevel.HARD


def _length(vector: Vec3) -> float:
    return math.sqrt(sum(component * component for component in vector))


def _dot(left: Vec3, right: Vec3) -> float:
    return sum(a * b for a, b in zip(left, right, strict=True))


class SurfaceFrame(DomainModel):
    origin: Vec3
    u_axis: Vec3
    v_axis: Vec3
    normal: Vec3

    @model_validator(mode="after")
    def validate_orthonormal(self) -> SurfaceFrame:
        axes = (self.u_axis, self.v_axis, self.normal)
        if any(not math.isclose(_length(axis), 1.0, abs_tol=1e-5) for axis in axes):
            raise ValueError("surface frame axes must be unit vectors")
        pairs = ((self.u_axis, self.v_axis), (self.u_axis, self.normal), (self.v_axis, self.normal))
        if any(not math.isclose(_dot(a, b), 0.0, abs_tol=1e-5) for a, b in pairs):
            raise ValueError("surface frame axes must be mutually orthogonal")
        return self


class SceneSurface(DomainModel):
    surface_id: str = Field(min_length=1)
    element_id: str = Field(min_length=1)
    frame: SurfaceFrame
    width_m: PositiveMeters
    height_m: PositiveMeters
    semantic_role: SemanticRole = SemanticRole.UNKNOWN


class CanonicalScene(DomainModel):
    schema_version: str = "1.0.0"
    source: SourceModelRef
    coordinate_system: CoordinateSystem
    elements: tuple[SceneElement, ...] = ()
    surfaces: tuple[SceneSurface, ...] = ()

    @model_validator(mode="after")
    def validate_references(self) -> CanonicalScene:
        element_ids = [element.scene_element_id for element in self.elements]
        if len(element_ids) != len(set(element_ids)):
            raise ValueError("scene element IDs must be unique")
        surface_ids = [surface.surface_id for surface in self.surfaces]
        if len(surface_ids) != len(set(surface_ids)):
            raise ValueError("surface IDs must be unique")
        missing = {surface.element_id for surface in self.surfaces} - set(element_ids)
        if missing:
            raise ValueError(f"surfaces reference missing elements: {sorted(missing)}")
        return self

