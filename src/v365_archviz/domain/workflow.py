"""View-set and durable workflow state contracts."""

from __future__ import annotations

from enum import Enum

from pydantic import Field, model_validator

from v365_archviz.domain.common import DomainModel, Vec3


class ViewRole(str, Enum):
    OVERALL = "overall"
    CONTEXT = "context"
    HERO = "hero"
    DETAIL = "detail"
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


class GenerationProfile(str, Enum):
    PREVIEW_FAST = "preview_fast"
    BASE_PRO = "base_pro"
    STRICT_GEOMETRY = "strict_geometry"
    MARKETING_HERO = "marketing_hero"


class ConditioningPack(DomainModel):
    view_id: str = Field(min_length=1)
    camera_ref: str = Field(min_length=1)
    base_rgb_ref: str = Field(min_length=1)
    clay_ref: str = Field(min_length=1)
    depth_ref: str = Field(min_length=1)
    normal_ref: str = Field(min_length=1)
    instance_id_ref: str = Field(min_length=1)
    semantic_ref: str = Field(min_length=1)
    edges_ref: str = Field(min_length=1)
    material_id_ref: str | None = None
    visibility_ref: str | None = None


class ViewSetGenerationRequest(DomainModel):
    request_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    model_revision: str = Field(min_length=1)
    design_revision: str = Field(min_length=1)
    view_set_id: str = Field(min_length=1)
    profile: GenerationProfile
    prompt_version: str = Field(min_length=1)
    provider_model: str = Field(min_length=1)
    conditioning_packs: tuple[ConditioningPack, ...]
    reference_image_refs: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_packs(self) -> ViewSetGenerationRequest:
        view_ids = [pack.view_id for pack in self.conditioning_packs]
        if not view_ids:
            raise ValueError("a view-set generation request must contain at least one view")
        if len(view_ids) != len(set(view_ids)):
            raise ValueError("conditioning pack view IDs must be unique")
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
