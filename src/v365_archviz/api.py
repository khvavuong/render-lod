"""HTTP control-plane entrypoint."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from v365_archviz import __version__
from v365_archviz.application.create_generation_job import CreateGenerationJob
from v365_archviz.application.plan_cameras import PlanStandardCameras
from v365_archviz.application.plan_design import PlanDesign
from v365_archviz.artifacts import atomic_write
from v365_archviz.config import Settings
from v365_archviz.domain.design import DesignBrief, DesignDNA
from v365_archviz.domain.scene import CanonicalScene
from v365_archviz.domain.workflow import GenerationProfile, WorkflowState
from v365_archviz.providers.local_jobs import LocalJobRepository

app = FastAPI(
    title="V365 ArchViz Control Plane",
    version=__version__,
    description="Geometry-first multi-view architectural visualization API",
)


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"] = "ok"
    version: str


class CapabilityResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    local_rvt_inspection: bool
    aps_geometry_extraction: bool
    gemini_image_generation: bool


class CreateDesignRevisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_revision: str = Field(min_length=1)
    brief: DesignBrief


class DesignRevisionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str
    model_revision: str
    design_revision: str
    design_dna_ref: str
    brief_ref: str


class CreateViewSetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_revision: str = Field(min_length=1)
    profile: GenerationProfile = GenerationProfile.PREVIEW_FAST


class ViewSetJobResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str
    view_set_id: str
    design_revision: str
    state: WorkflowState
    created: bool


class ViewActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    view_set_id: str = Field(min_length=1)


def _settings() -> Settings:
    return Settings.from_env()


def _repository(settings: Settings) -> LocalJobRepository:
    return LocalJobRepository(settings.artifact_dir / "metadata")


def _design_directory(
    artifact_dir: Path, model_revision: str, design_revision: str
) -> Path:
    return artifact_dir / "scenes" / model_revision / "designs" / design_revision


@app.get("/healthz", response_model=HealthResponse, tags=["system"])
def health() -> HealthResponse:
    return HealthResponse(version=__version__)


@app.get("/v1/system/capabilities", response_model=CapabilityResponse, tags=["system"])
def capabilities() -> CapabilityResponse:
    settings = Settings.from_env()
    return CapabilityResponse(
        local_rvt_inspection=True,
        aps_geometry_extraction=settings.aps_configured,
        gemini_image_generation=settings.gemini_configured,
    )


@app.post(
    "/v1/projects/{project_id}/design-revisions",
    response_model=DesignRevisionResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["design"],
)
def create_design_revision(
    project_id: str, request: CreateDesignRevisionRequest
) -> DesignRevisionResponse:
    if request.brief.project_id != project_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="brief project_id must match the route project_id",
        )
    settings = _settings()
    scene_path = (
        settings.artifact_dir
        / "scenes"
        / request.model_revision
        / "canonical_scene.json"
    )
    if not scene_path.is_file():
        raise HTTPException(status_code=404, detail="canonical scene not found")
    scene = CanonicalScene.model_validate_json(scene_path.read_text(encoding="utf-8"))
    revision = PlanDesign.revision(scene, request.brief)
    target = _design_directory(settings.artifact_dir, request.model_revision, revision)
    brief_path = target / "design_brief.json"
    atomic_write(brief_path, request.brief.model_dump_json(indent=2).encode() + b"\n")
    design = PlanDesign().execute(scene_path, brief_path)
    return DesignRevisionResponse(
        project_id=project_id,
        model_revision=request.model_revision,
        design_revision=design.design_revision,
        design_dna_ref=str(target / "design_dna.json"),
        brief_ref=str(brief_path),
    )


@app.post(
    "/v1/design-revisions/{design_revision}/view-sets",
    response_model=ViewSetJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["generation"],
)
def create_view_set(
    design_revision: str, request: CreateViewSetRequest
) -> ViewSetJobResponse:
    settings = _settings()
    scene_path = (
        settings.artifact_dir
        / "scenes"
        / request.model_revision
        / "canonical_scene.json"
    )
    design_path = (
        _design_directory(settings.artifact_dir, request.model_revision, design_revision)
        / "design_dna.json"
    )
    if not scene_path.is_file() or not design_path.is_file():
        raise HTTPException(status_code=404, detail="design revision not found")
    design = DesignDNA.model_validate_json(
        design_path.read_text(encoding="utf-8")
    )
    if design.design_revision != design_revision:
        raise HTTPException(status_code=409, detail="design revision is not immutable")
    view_set = PlanStandardCameras().execute(scene_path, design_path)
    created = CreateGenerationJob().execute(
        _repository(settings),
        project_id=design.project_id,
        model_revision=request.model_revision,
        design_revision=design_revision,
        view_set=view_set,
        profile=request.profile,
    )
    job = created.job
    if created.created:
        job = job.transition(
            WorkflowState.RENDERING_PASSES,
            artifact_refs=(str(design_path), str(design_path.parent / "view_set.json")),
        )
        _repository(settings).save(job)
    return ViewSetJobResponse(
        job_id=job.job_id,
        view_set_id=job.view_set_id,
        design_revision=job.design_revision,
        state=job.state,
        created=created.created,
    )


@app.get(
    "/v1/view-sets/{view_set_id}",
    response_model=ViewSetJobResponse,
    tags=["generation"],
)
def get_view_set(view_set_id: str) -> ViewSetJobResponse:
    try:
        job = _repository(_settings()).get_by_view_set(view_set_id)
    except OSError as exc:
        raise HTTPException(status_code=404, detail="view set not found") from exc
    return ViewSetJobResponse(
        job_id=job.job_id,
        view_set_id=job.view_set_id,
        design_revision=job.design_revision,
        state=job.state,
        created=False,
    )


def _transition_view_set(
    view_set_id: str, target: WorkflowState
) -> ViewSetJobResponse:
    repository = _repository(_settings())
    try:
        job = repository.get_by_view_set(view_set_id)
        updated = job.transition(target)
    except OSError as exc:
        raise HTTPException(status_code=404, detail="view set not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    repository.save(updated)
    return ViewSetJobResponse(
        job_id=updated.job_id,
        view_set_id=updated.view_set_id,
        design_revision=updated.design_revision,
        state=updated.state,
        created=False,
    )


@app.post(
    "/v1/views/{view_id}/approve",
    response_model=ViewSetJobResponse,
    tags=["review"],
)
def approve_view(view_id: str, request: ViewActionRequest) -> ViewSetJobResponse:
    del view_id
    return _transition_view_set(request.view_set_id, WorkflowState.COMPOSING_BOARD)


@app.post(
    "/v1/views/{view_id}/repair",
    response_model=ViewSetJobResponse,
    tags=["review"],
)
def repair_view(view_id: str, request: ViewActionRequest) -> ViewSetJobResponse:
    del view_id
    return _transition_view_set(request.view_set_id, WorkflowState.REPAIRING)
