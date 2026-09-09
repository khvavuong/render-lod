"""HTTP control-plane entrypoint."""

from __future__ import annotations

import os
import re
import uuid
from pathlib import Path
from typing import Literal
from urllib.parse import unquote

from fastapi import FastAPI, Header, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from v365_archviz import __version__
from v365_archviz.application.create_generation_job import CreateGenerationJob
from v365_archviz.application.inspect_model import InspectModel
from v365_archviz.application.plan_cameras import PlanStandardCameras
from v365_archviz.application.plan_design import PlanDesign
from v365_archviz.artifacts import atomic_write
from v365_archviz.config import Settings
from v365_archviz.domain.design import DesignBrief, DesignDNA
from v365_archviz.domain.scene import CanonicalScene
from v365_archviz.domain.workflow import GenerationProfile, WorkflowState
from v365_archviz.errors import InvalidModelError
from v365_archviz.providers.local_dispatcher import LocalGenerationDispatcher
from v365_archviz.providers.local_jobs import LocalJobRepository
from v365_archviz.providers.local_rvt import LocalRvtInspector

OutputKind = Literal["image", "board", "video"]
MAX_RVT_UPLOAD_BYTES = 2 * 1024 * 1024 * 1024

app = FastAPI(
    title="V365 ArchViz Control Plane",
    version=__version__,
    description="Geometry-first multi-view architectural visualization API",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-Filename"],
)

_generation_dispatcher = LocalGenerationDispatcher()

SAFE_IDENTIFIER_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"
_SAFE_IDENTIFIER = re.compile(SAFE_IDENTIFIER_PATTERN)


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"] = "ok"
    version: str


class CapabilityResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    local_rvt_inspection: bool
    aps_geometry_extraction: bool
    gemini_image_generation: bool


class ActiveModelResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_revision: str = Field(pattern=SAFE_IDENTIFIER_PATTERN)


class ModelUploadResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_revision: str = Field(pattern=SAFE_IDENTIFIER_PATTERN)
    file_name: str
    size_bytes: int = Field(gt=0)
    ready: bool


class CreateDesignRevisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_revision: str = Field(pattern=SAFE_IDENTIFIER_PATTERN)
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

    model_revision: str = Field(pattern=SAFE_IDENTIFIER_PATTERN)
    profile: GenerationProfile = GenerationProfile.PREVIEW_FAST


class ViewSetJobResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str
    trace_id: str
    view_set_id: str
    design_revision: str
    state: WorkflowState
    created: bool
    error_code: str | None = None
    error_message: str | None = None


class ViewActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    view_set_id: str = Field(pattern=SAFE_IDENTIFIER_PATTERN)


class OutputArtifactResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    kind: OutputKind
    title: str
    url: str
    view_id: str | None = None


class ViewSetOutputsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outputs: tuple[OutputArtifactResponse, ...]


def _settings() -> Settings:
    return Settings.from_env()


def _repository(settings: Settings) -> LocalJobRepository:
    return LocalJobRepository(settings.artifact_dir / "metadata")


def _design_directory(artifact_dir: Path, model_revision: str, design_revision: str) -> Path:
    return artifact_dir / "scenes" / model_revision / "designs" / design_revision


def _require_safe_identifier(value: str, label: str) -> None:
    if not _SAFE_IDENTIFIER.fullmatch(value):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"invalid {label}",
        )


def _output_files(view_set_id: str) -> dict[str, tuple[Path, OutputKind, str, str | None]]:
    try:
        job = _repository(_settings()).get_by_view_set(view_set_id)
    except OSError as exc:
        raise HTTPException(status_code=404, detail="view set not found") from exc
    settings = _settings()
    generated = settings.artifact_dir / "generated" / job.model_revision / job.design_revision
    files: dict[str, tuple[Path, OutputKind, str, str | None]] = {}
    for view_dir in sorted(generated.glob("view-*")):
        candidates = tuple(view_dir.glob("refined.*"))
        if len(candidates) == 1 and candidates[0].is_file():
            asset_id = f"image-{view_dir.name}"
            files[asset_id] = (candidates[0], "image", view_dir.name.upper(), view_dir.name)
    board = generated / "viewset_board.jpg"
    if board.is_file():
        files["board"] = (board, "board", "Bộ 6 góc nhìn", None)
    video_root = settings.artifact_dir / "videos" / job.model_revision / job.design_revision
    videos = sorted(video_root.glob("*/showreel.mp4"), key=lambda path: path.stat().st_mtime)
    if videos:
        files["video"] = (videos[-1], "video", "Video trình diễn", None)
    return files


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


@app.get("/v1/models/latest", response_model=ActiveModelResponse, tags=["models"])
def latest_model() -> ActiveModelResponse:
    scenes = _settings().artifact_dir / "scenes"
    candidates = tuple(scenes.glob("*/canonical_scene.json"))
    if not candidates:
        raise HTTPException(status_code=404, detail="no canonical model is available")
    latest = max(candidates, key=lambda path: path.stat().st_mtime_ns)
    return ActiveModelResponse(model_revision=latest.parent.name)


@app.post(
    "/v1/models",
    response_model=ModelUploadResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["models"],
)
async def upload_model(
    request: Request,
    x_filename: str = Header(..., min_length=1, max_length=512),
) -> ModelUploadResponse:
    file_name = Path(unquote(x_filename)).name
    if Path(file_name).suffix.lower() != ".rvt":
        raise HTTPException(status_code=422, detail="only .rvt files are supported")
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > MAX_RVT_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="RVT file exceeds the 2 GiB limit")

    settings = _settings()
    incoming = settings.artifact_dir / "uploads" / ".incoming"
    incoming.mkdir(parents=True, exist_ok=True)
    temporary = incoming / f"{uuid.uuid4().hex}.rvt"
    size_bytes = 0
    try:
        with temporary.open("xb") as output:
            async for chunk in request.stream():
                size_bytes += len(chunk)
                if size_bytes > MAX_RVT_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="RVT file exceeds the 2 GiB limit")
                output.write(chunk)
        if not size_bytes:
            raise HTTPException(status_code=422, detail="RVT file is empty")
        inspection = LocalRvtInspector().inspect(temporary)
        model_revision = inspection.sha256[:16]
        target = settings.artifact_dir / "uploads" / model_revision / "source.rvt"
        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(temporary, target)
        InspectModel().execute(target, settings.artifact_dir)
    except InvalidModelError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        temporary.unlink(missing_ok=True)

    ready = (settings.artifact_dir / "scenes" / model_revision / "canonical_scene.json").is_file()
    return ModelUploadResponse(
        model_revision=model_revision,
        file_name=file_name,
        size_bytes=size_bytes,
        ready=ready,
    )


@app.get("/v1/brand/logo", response_class=FileResponse, tags=["system"])
def brand_logo() -> FileResponse:
    logo = Path(__file__).resolve().parents[2] / "resource" / "logo" / "logo_vertical.png"
    if not logo.is_file():
        raise HTTPException(status_code=404, detail="brand logo not found")
    return FileResponse(logo)


@app.post(
    "/v1/projects/{project_id}/design-revisions",
    response_model=DesignRevisionResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["design"],
)
def create_design_revision(
    project_id: str, request: CreateDesignRevisionRequest
) -> DesignRevisionResponse:
    _require_safe_identifier(project_id, "project_id")
    if request.brief.project_id != project_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="brief project_id must match the route project_id",
        )
    settings = _settings()
    scene_path = settings.artifact_dir / "scenes" / request.model_revision / "canonical_scene.json"
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
def create_view_set(design_revision: str, request: CreateViewSetRequest) -> ViewSetJobResponse:
    _require_safe_identifier(design_revision, "design_revision")
    settings = _settings()
    scene_path = settings.artifact_dir / "scenes" / request.model_revision / "canonical_scene.json"
    design_path = (
        _design_directory(settings.artifact_dir, request.model_revision, design_revision)
        / "design_dna.json"
    )
    if not scene_path.is_file() or not design_path.is_file():
        raise HTTPException(status_code=404, detail="design revision not found")
    design = DesignDNA.model_validate_json(design_path.read_text(encoding="utf-8"))
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
    if settings.local_worker_enabled and job.state not in {
        WorkflowState.COMPLETED,
        WorkflowState.FAILED,
    }:
        _generation_dispatcher.submit(job.job_id)
    return ViewSetJobResponse(
        job_id=job.job_id,
        trace_id=job.trace_id,
        view_set_id=job.view_set_id,
        design_revision=job.design_revision,
        state=job.state,
        created=created.created,
        error_code=job.error_code,
        error_message=job.error_message,
    )


@app.get(
    "/v1/view-sets/{view_set_id}",
    response_model=ViewSetJobResponse,
    tags=["generation"],
)
def get_view_set(view_set_id: str) -> ViewSetJobResponse:
    _require_safe_identifier(view_set_id, "view_set_id")
    try:
        job = _repository(_settings()).get_by_view_set(view_set_id)
    except OSError as exc:
        raise HTTPException(status_code=404, detail="view set not found") from exc
    return ViewSetJobResponse(
        job_id=job.job_id,
        trace_id=job.trace_id,
        view_set_id=job.view_set_id,
        design_revision=job.design_revision,
        state=job.state,
        created=False,
        error_code=job.error_code,
        error_message=job.error_message,
    )


@app.get(
    "/v1/view-sets/{view_set_id}/outputs",
    response_model=ViewSetOutputsResponse,
    tags=["generation"],
)
def get_view_set_outputs(view_set_id: str) -> ViewSetOutputsResponse:
    _require_safe_identifier(view_set_id, "view_set_id")
    outputs = tuple(
        OutputArtifactResponse(
            id=asset_id,
            kind=kind,
            title=title,
            view_id=view_id,
            url=f"/v1/view-sets/{view_set_id}/outputs/{asset_id}",
        )
        for asset_id, (_, kind, title, view_id) in _output_files(view_set_id).items()
    )
    return ViewSetOutputsResponse(outputs=outputs)


@app.get(
    "/v1/view-sets/{view_set_id}/outputs/{asset_id}",
    response_class=FileResponse,
    tags=["generation"],
)
def download_view_set_output(view_set_id: str, asset_id: str) -> FileResponse:
    _require_safe_identifier(view_set_id, "view_set_id")
    _require_safe_identifier(asset_id, "asset_id")
    artifact = _output_files(view_set_id).get(asset_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="output artifact not found")
    path, _, _, _ = artifact
    return FileResponse(path, filename=path.name)


def _transition_view_set(view_set_id: str, target: WorkflowState) -> ViewSetJobResponse:
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
        trace_id=updated.trace_id,
        view_set_id=updated.view_set_id,
        design_revision=updated.design_revision,
        state=updated.state,
        created=False,
        error_code=updated.error_code,
        error_message=updated.error_message,
    )


@app.post(
    "/v1/views/{view_id}/approve",
    response_model=ViewSetJobResponse,
    tags=["review"],
)
def approve_view(view_id: str, request: ViewActionRequest) -> ViewSetJobResponse:
    _require_safe_identifier(view_id, "view_id")
    return _transition_view_set(request.view_set_id, WorkflowState.COMPOSING_BOARD)


@app.post(
    "/v1/views/{view_id}/repair",
    response_model=ViewSetJobResponse,
    tags=["review"],
)
def repair_view(view_id: str, request: ViewActionRequest) -> ViewSetJobResponse:
    _require_safe_identifier(view_id, "view_id")
    return _transition_view_set(request.view_set_id, WorkflowState.REPAIRING)
