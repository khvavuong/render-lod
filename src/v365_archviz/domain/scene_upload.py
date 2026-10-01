"""A site plan sent by an editor that already knows what every object is.

Site Forma models its buildings as oriented boxes and its ground as flat
polygons, each with a known role. Nothing here is guessed from names or
geometry the way an IFC import has to: the roles arrive with the objects.
"""

from __future__ import annotations

import math
from typing import Literal

from pydantic import Field, model_validator

from v365_archviz.domain.common import DomainModel

SCENE_UPLOAD_VERSION: Literal["site-forma-scene-v1"] = "site-forma-scene-v1"
UPLOAD_IDENTIFIER_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"

BuildingRole = Literal["main_shed", "office_block", "utility_block"]
SurfaceRole = Literal[
    "site_ground",
    "site_road",
    "sidewalk",
    "parking",
    "landscape_zone",
    "loading_zone",
    "service_yard",
]

Point2 = tuple[float, float]


class UploadBuilding(DomainModel):
    """A box standing on the ground, rotated counter-clockwise about its base centre."""

    id: str = Field(pattern=UPLOAD_IDENTIFIER_PATTERN)
    name: str = Field(default="", max_length=200)
    role: BuildingRole
    center: Point2
    base_z: float = 0.0
    width_m: float = Field(gt=0.5, le=2000)
    length_m: float = Field(gt=0.5, le=2000)
    height_m: float = Field(gt=0.5, le=500)
    rotation_rad: float = 0.0
    #: Storeys the editor gives the building; an office's floor count is part of its design.
    floors: int | None = Field(default=None, ge=1, le=200)

    @model_validator(mode="after")
    def validate_finite(self) -> UploadBuilding:
        values = (*self.center, self.base_z, self.rotation_rad)
        if not all(math.isfinite(value) for value in values):
            raise ValueError("building coordinates must be finite")
        return self


class UploadContextBuilding(DomainModel):
    """A neighbouring building outside the site: a footprint extruded to a height."""

    id: str = Field(pattern=UPLOAD_IDENTIFIER_PATTERN)
    footprint: tuple[Point2, ...] = Field(min_length=3, max_length=200)
    height_m: float = Field(gt=0.5, le=500)

    @model_validator(mode="after")
    def validate_finite(self) -> UploadContextBuilding:
        if not all(math.isfinite(value) for point in self.footprint for value in point):
            raise ValueError("context footprint coordinates must be finite")
        return self


class UploadSurface(DomainModel):
    """A flat ground layer inside the site, already triangulated by the editor.

    `vertices` holds x, y, z triples in metres; `faces` holds vertex index
    triples. Ground outside the site is not sent: the camera planner frames
    aerials to every surface with a site role, so a street beyond the fence
    would push the camera back and shrink the project.
    """

    id: str = Field(pattern=UPLOAD_IDENTIFIER_PATTERN)
    role: SurfaceRole
    vertices: tuple[float, ...] = Field(min_length=9, max_length=600_000)
    faces: tuple[int, ...] = Field(min_length=3, max_length=600_000)

    @model_validator(mode="after")
    def validate_mesh(self) -> UploadSurface:
        if len(self.vertices) % 3 or len(self.faces) % 3:
            raise ValueError("vertices and faces must be flat triples")
        if not all(math.isfinite(value) for value in self.vertices):
            raise ValueError("surface vertices must be finite")
        count = len(self.vertices) // 3
        if any(index < 0 or index >= count for index in self.faces):
            raise ValueError("surface face index out of range")
        return self


class SceneUpload(DomainModel):
    schema_version: Literal["site-forma-scene-v1"] = SCENE_UPLOAD_VERSION
    project_id: str = Field(pattern=UPLOAD_IDENTIFIER_PATTERN)
    name: str = Field(default="", max_length=200)
    buildings: tuple[UploadBuilding, ...] = Field(min_length=1, max_length=400)
    context_buildings: tuple[UploadContextBuilding, ...] = Field(default=(), max_length=2000)
    surfaces: tuple[UploadSurface, ...] = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def validate_scene(self) -> SceneUpload:
        ids = [
            *(item.id for item in self.buildings),
            *(item.id for item in self.context_buildings),
            *(item.id for item in self.surfaces),
        ]
        if len(ids) != len(set(ids)):
            raise ValueError("scene object IDs must be unique")
        if not any(surface.role == "site_ground" for surface in self.surfaces):
            raise ValueError("a scene needs the site ground")
        return self
