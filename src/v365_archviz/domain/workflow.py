"""View-set and durable workflow state contracts."""

from __future__ import annotations

from enum import Enum

from pydantic import Field, model_validator

from v365_archviz.domain.common import DomainModel, Vec3


class ViewRole(str, Enum):
    OVERALL = "overall"
    CONTEXT = "context"
    OFFICE_HERO = "office_hero"
    LOADING_DETAIL = "loading_detail"


class Camera(DomainModel):
    view_id: str = Field(min_length=1)
    role: ViewRole
    position: Vec3
    target: Vec3
    focal_length_mm: float = Field(gt=0)
    sensor_width_mm: float = Field(gt=0)
    aspect_ratio: str = Field(pattern=r"^\d+:\d+$")

    @model_validator(mode="after")
    def validate_pose(self) -> Camera:
        if self.position == self.target:
            raise ValueError("camera position and target must differ")
        return self


class ViewSet(DomainModel):
    view_set_id: str = Field(min_length=1)
    design_revision: str = Field(min_length=1)
    cameras: tuple[Camera, ...]

    @model_validator(mode="after")
    def validate_cameras(self) -> ViewSet:
        view_ids = [camera.view_id for camera in self.cameras]
        if len(view_ids) != len(set(view_ids)):
            raise ValueError("view IDs must be unique")
        return self


class WorkflowState(str, Enum):
    RESOLVING_MODEL = "resolving_model"
    EXTRACTING_SCENE = "extracting_scene"
    CLASSIFYING_SCENE = "classifying_scene"
    DESIGN_PLANNING = "design_planning"
    DESIGN_VALIDATION = "design_validation"
    NEEDS_INPUT = "needs_input"
    BUILDING_SCENE = "building_scene"
    PLANNING_CAMERAS = "planning_cameras"
    RENDERING_PASSES = "rendering_passes"
    GENERATING_VIEWSET = "generating_viewset"
    VALIDATING = "validating"
    REPAIRING = "repairing"
    HUMAN_REVIEW = "human_review"
    COMPOSING_BOARD = "composing_board"
    COMPLETED = "completed"
    FAILED = "failed"

