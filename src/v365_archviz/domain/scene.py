"""Canonical geometry contracts independent of Autodesk transport formats."""

from __future__ import annotations

import math
from enum import Enum

from pydantic import Field, model_validator

from v365_archviz.domain.building_kind import (
    BuildingFeatures,
    BuildingKind,
    BuildingMaterial,
    Compass,
)
from v365_archviz.domain.common import DomainModel, Matrix4x4, PositiveMeters, Vec3
from v365_archviz.domain.gate import GatePart


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
    SITE_GROUND = "site_ground"
    SITE_ROAD = "site_road"
    SIDEWALK = "sidewalk"
    UTILITY_BLOCK = "utility_block"
    PARKING = "parking"
    MAIN_ENTRANCE = "main_entrance"
    SECONDARY_ENTRANCE = "secondary_entrance"
    LANDSCAPE_ZONE = "landscape_zone"
    ROOF = "roof"
    SITE_BOUNDARY = "site_boundary"
    PRIMARY_FACADE = "primary_facade"
    #: A thin elevated plane too small or too narrow to be a shed roof — the
    #: awnings a LOD200 model draws along a building edge. Kept apart from ROOF
    #: so a roof finish is not applied to the canopies instead of the roof.
    CANOPY = "canopy"
    #: A dock door. It is evidence that goods move through this facade, but it
    #: is a part of the building rather than a piece of ground: pointed at as if
    #: it were a yard, the camera stands against a three-metre door and fills the
    #: frame with it.
    LOADING_DOCK = "loading_dock"
    #: A wall. It is part of a building's skin, never a building of its own; the
    #: geometric mass rules must not see it, or a shed's own cladding is counted
    #: as a dozen utility buildings standing on the site.
    ENVELOPE_PANEL = "envelope_panel"


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
    #: Storeys, when the source model states them.
    storeys: int | None = Field(default=None, ge=1, le=200)
    #: What the building is, its front and the parts drawn on it, when the source states them.
    kind: BuildingKind | None = None
    front: Compass | None = None
    features: BuildingFeatures | None = None
    wall_material: BuildingMaterial | None = None
    roof_material: BuildingMaterial | None = None
    #: The plan outline of a flat element when the source states it: the plot a fence follows,
    #: the opening a gate leaves in it.
    outline: tuple[tuple[float, float], ...] | None = Field(default=None, min_length=3)
    #: The blocks a gate is drawn with, when the source draws them.
    gate_parts: tuple[GatePart, ...] | None = None


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
