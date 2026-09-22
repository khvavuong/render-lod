"""HTTP control-plane entrypoint."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import re
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Literal
from urllib.parse import unquote

from fastapi import (
    FastAPI,
    File,
    Form,
    Header,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field, model_validator
from starlette.concurrency import run_in_threadpool

from v365_archviz import __version__
from v365_archviz.application.analyze_model_capabilities import AnalyzeModelDesignCapabilities
from v365_archviz.application.apply_view_edit import (
    EDITABLE_STATES,
    MAX_CANDIDATES,
    MAX_REFERENCES,
    ApplyViewEdit,
    CommitViewEdit,
    view_directory,
)
from v365_archviz.application.build_canonical_scene import BuildCanonicalScene
from v365_archviz.application.compile_user_intent import CompileUserRenderIntent
from v365_archviz.application.create_generation_job import CreateGenerationJob
from v365_archviz.application.create_video_job import CreateVideoJob
from v365_archviz.application.extract_ifc import ExtractIfc
from v365_archviz.application.inspect_model import InspectModel
from v365_archviz.application.plan_cameras import PlanStandardCameras
from v365_archviz.application.plan_design import PlanDesign
from v365_archviz.application.plan_industrial_context import PlanIndustrialContext
from v365_archviz.application.restore_view_edit import RestoreViewEdit
from v365_archviz.application.view_edit_store import (
    ViewEditRecord,
    ViewEditStore,
    media_type_of,
)
from v365_archviz.artifacts import atomic_write
from v365_archviz.config import Settings
from v365_archviz.domain.controlled_realism import CertificationReport, CertificationState
from v365_archviz.domain.design import DesignBrief, DesignDNA, IndustrialContextPlan
from v365_archviz.domain.jobs import GenerationJob
from v365_archviz.domain.render_intent import (
    DESIGN_OPTIONS,
    DesignOptionsCatalog,
    IntentWarning,
    ModelDesignCapabilities,
    UserRenderIntent,
)
from v365_archviz.domain.scene import CanonicalScene
from v365_archviz.domain.video_jobs import VideoJob, VideoJobState
from v365_archviz.domain.workflow import GenerationProfile, RenderProfile, ViewSet, WorkflowState
from v365_archviz.errors import (
    ConfigurationError,
    InvalidModelError,
    ProviderError,
    V365Error,
)
from v365_archviz.providers.aps.model_derivative import ApsModelDerivativeClient
from v365_archviz.providers.local_dispatcher import LocalGenerationDispatcher
from v365_archviz.providers.local_edit_dispatcher import LocalEditDispatcher, Publish
from v365_archviz.providers.local_jobs import LocalJobRepository
from v365_archviz.providers.local_rvt import LocalRvtInspector
from v365_archviz.providers.local_video_dispatcher import LocalVideoDispatcher
from v365_archviz.providers.local_video_jobs import LocalVideoJobRepository

OutputKind = Literal["image", "board", "video"]
# Read once here rather than in each signature: a call in an argument default
# is evaluated at import, which is exactly what FastAPI wants and what B008
# warns about everywhere else.
_MASK_FILE = File(None)
# Who asked, carried as a header so the multipart body reaches this service
# exactly as the browser built it. The proxy in front knows the user; this
# service only records the name it is handed.
_EDIT_USER_HEADER = Header("unknown", alias="X-Edit-User")
_REFERENCE_FILES = File(None)
MAX_RVT_UPLOAD_BYTES = 2 * 1024 * 1024 * 1024
MAX_REFERENCE_UPLOAD_BYTES = 20 * 1024 * 1024

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
_video_dispatcher = LocalVideoDispatcher()
_edit_dispatcher = LocalEditDispatcher()

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
    openai_image_generation: bool
    active_image_provider: str
    veo_video_generation: bool


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
    intent: UserRenderIntent | None = None
    brief: DesignBrief | None = None
    preview_token: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def require_one_contract(self) -> CreateDesignRevisionRequest:
        if (self.intent is None) == (self.brief is None):
            raise ValueError("provide exactly one of intent or brief")
        return self


class DesignRevisionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str
    model_revision: str
    design_revision: str
    design_dna_ref: str
    brief_ref: str
    normalized_intent: UserRenderIntent | None = None
    warnings: tuple[IntentWarning, ...] = ()
    preset_catalog_version: str | None = None


class DesignPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(pattern=SAFE_IDENTIFIER_PATTERN)
    intent: UserRenderIntent


class DesignPreviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_revision: str
    preview_token: str = Field(pattern=r"^[a-f0-9]{64}$")
    normalized_intent: UserRenderIntent
    capabilities: ModelDesignCapabilities
    industrial_context: IndustrialContextPlan
    warnings: tuple[IntentWarning, ...] = ()


class CreateViewSetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_revision: str = Field(pattern=SAFE_IDENTIFIER_PATTERN)
    profile: GenerationProfile = GenerationProfile.PREVIEW_FAST
    render_profile: RenderProfile = RenderProfile.STANDARD_EEVEE
    reference_ids: tuple[str, ...] = Field(default=(), max_length=2)


class ReferenceUploadResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reference_id: str = Field(pattern=r"^[a-f0-9]{64}$")
    role: Literal["factory_design_reference", "context_realism_reference"]
    file_name: str
    width: int = Field(gt=0)
    height: int = Field(gt=0)


class ViewSetJobResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str
    trace_id: str
    view_set_id: str
    design_revision: str
    state: WorkflowState
    certification_state: CertificationState = CertificationState.BASE_PBR
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


class VideoJobResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    video_job_id: str
    view_set_id: str
    state: VideoJobState
    created: bool
    estimated_cost_usd: float
    output_url: str | None = None
    error_code: str | None = None
    error_message: str | None = None


class ViewEditResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    edit_id: str
    view_id: str
    sequence: int
    kind: str
    state: str
    prompt: str
    candidate_count: int
    chosen: int | None
    created_by: str
    created_at: str
    committed_at: str | None
    previous_url: str
    candidate_urls: tuple[str, ...]


class ViewEditListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    edits: tuple[ViewEditResponse, ...]
    #: How much of the bounded repair budget this view set has already spent.
    attempt: int
    editable: bool


class StartViewEditResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    edit_id: str
    view_id: str
    view_set_id: str


class CommitViewEditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chosen: int = Field(ge=0, lt=MAX_CANDIDATES)


class RestoreViewEditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    created_by: str = Field(default="unknown", min_length=1)


def _settings() -> Settings:
    return Settings.from_env()


def _repository(settings: Settings) -> LocalJobRepository:
    return LocalJobRepository(settings.artifact_dir / "metadata")


def _video_repository(settings: Settings) -> LocalVideoJobRepository:
    return LocalVideoJobRepository(settings.artifact_dir / "metadata")


def _video_job_response(job: VideoJob, *, created: bool) -> VideoJobResponse:
    return VideoJobResponse(
        video_job_id=job.video_job_id,
        view_set_id=job.view_set_id,
        state=job.state,
        created=created,
        estimated_cost_usd=job.estimated_cost_usd,
        output_url=(
            f"/v1/video-jobs/{job.video_job_id}/output"
            if job.state is VideoJobState.COMPLETED and job.output_ref
            else None
        ),
        error_code=job.error_code,
        error_message=job.error_message,
    )


def _prepare_uploaded_model(source: Path, settings: Settings) -> None:
    """Translate and canonicalize one uncached RVT outside the ASGI event loop."""

    with ApsModelDerivativeClient(settings) as client:
        extraction = ExtractIfc(client).execute(source, settings.artifact_dir)
    BuildCanonicalScene().execute(source, extraction.ifc_path, settings.artifact_dir)


def _preview_token(
    model_revision: str,
    project_id: str,
    normalized_intent: UserRenderIntent,
) -> str:
    payload = {
        "model_revision": model_revision,
        "project_id": project_id,
        "intent": normalized_intent.model_dump(mode="json"),
        "catalog_version": DESIGN_OPTIONS.catalog_version,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _design_directory(artifact_dir: Path, model_revision: str, design_revision: str) -> Path:
    return artifact_dir / "scenes" / model_revision / "designs" / design_revision


def _resolve_references(
    artifact_dir: Path, reference_ids: tuple[str, ...]
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    refs: list[str] = []
    roles: list[str] = []
    for reference_id in reference_ids:
        if not re.fullmatch(r"[a-f0-9]{64}", reference_id):
            raise HTTPException(status_code=422, detail="invalid reference ID")
        root = artifact_dir / "references" / reference_id
        metadata_path = root / "metadata.json"
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            source = root / str(metadata["stored_name"])
            role = str(metadata["role"])
        except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=404, detail="reference image not found") from exc
        if not source.is_file() or role not in {
            "factory_design_reference",
            "context_realism_reference",
        }:
            raise HTTPException(status_code=409, detail="reference metadata is invalid")
        refs.append(str(source))
        roles.append(role)
    return tuple(refs), tuple(roles)


def _with_active_quality_baseline(
    artifact_dir: Path,
    reference_refs: tuple[str, ...],
    reference_roles: tuple[str, ...],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Fill missing reference roles from the latest human-approved visual baseline."""

    required_roles = ("factory_design_reference", "context_realism_reference")
    refs = list(reference_refs)
    roles = list(reference_roles)
    manifest_path = artifact_dir / "quality_baselines" / "active.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        baseline_ids = manifest["reference_ids"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError):
        return reference_refs, reference_roles
    for role in required_roles:
        if role in roles:
            continue
        reference_id = baseline_ids.get(role)
        if not isinstance(reference_id, str):
            continue
        baseline_refs, baseline_roles = _resolve_references(artifact_dir, (reference_id,))
        refs.extend(baseline_refs)
        roles.extend(baseline_roles)
    return tuple(refs), tuple(roles)


def _certification_state(job: GenerationJob, settings: Settings) -> CertificationState:
    model_revision = job.model_revision
    design_revision = job.design_revision
    path = (
        settings.artifact_dir
        / "generated"
        / model_revision
        / design_revision
        / "certification_report.json"
    )
    if not path.is_file():
        return CertificationState.BASE_PBR
    try:
        return CertificationReport.model_validate_json(path.read_text(encoding="utf-8")).state
    except (OSError, ValueError):
        return CertificationState.BASE_PBR


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


@app.get("/v1/design-options", response_model=DesignOptionsCatalog, tags=["design"])
def design_options() -> DesignOptionsCatalog:
    """Expose the versioned server-owned catalog used to build render intent."""

    return DESIGN_OPTIONS


@app.get("/v1/system/capabilities", response_model=CapabilityResponse, tags=["system"])
def capabilities() -> CapabilityResponse:
    settings = Settings.from_env()
    return CapabilityResponse(
        local_rvt_inspection=True,
        aps_geometry_extraction=settings.aps_configured,
        gemini_image_generation=settings.gemini_configured,
        openai_image_generation=settings.openai_configured,
        active_image_provider=settings.image_provider,
        veo_video_generation=settings.gemini_configured,
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
    "/v1/references",
    response_model=ReferenceUploadResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["references"],
)
async def upload_reference(
    request: Request,
    x_filename: str = Header(..., min_length=1, max_length=512),
    x_reference_role: Literal["factory_design_reference", "context_realism_reference"] = Header(
        ...
    ),
) -> ReferenceUploadResponse:
    file_name = Path(unquote(x_filename)).name
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > MAX_REFERENCE_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="reference image exceeds 20 MiB")
    content = await request.body()
    if not content:
        raise HTTPException(status_code=422, detail="reference image is empty")
    if len(content) > MAX_REFERENCE_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="reference image exceeds 20 MiB")
    try:
        with Image.open(io.BytesIO(content)) as source:
            source.verify()
        with Image.open(io.BytesIO(content)) as source:
            width, height = source.size
            image_format = (source.format or "").lower()
    except (UnidentifiedImageError, OSError) as exc:
        raise HTTPException(status_code=422, detail="reference must be a valid image") from exc
    extensions = {"jpeg": ".jpg", "png": ".png", "webp": ".webp"}
    if image_format not in extensions:
        raise HTTPException(status_code=422, detail="reference must be JPEG, PNG or WebP")
    content_sha = hashlib.sha256(content).hexdigest()
    reference_id = hashlib.sha256(f"{x_reference_role}\n{content_sha}".encode()).hexdigest()
    root = _settings().artifact_dir / "references" / reference_id
    stored_name = f"source{extensions[image_format]}"
    atomic_write(root / stored_name, content)
    atomic_write(
        root / "metadata.json",
        json.dumps(
            {
                "schema_version": "1.0.0",
                "reference_id": reference_id,
                "role": x_reference_role,
                "file_name": file_name,
                "stored_name": stored_name,
                "content_sha256": content_sha,
                "width": width,
                "height": height,
                "allowed_influence": (
                    ["construction_detail", "material_response", "human_scale"]
                    if x_reference_role == "factory_design_reference"
                    else ["industrial_context", "roads", "atmosphere"]
                ),
                "prohibited_influence": ["project_geometry", "camera", "palette", "logo"],
            },
            ensure_ascii=False,
            indent=2,
        ).encode("utf-8")
        + b"\n",
    )
    return ReferenceUploadResponse(
        reference_id=reference_id,
        role=x_reference_role,
        file_name=file_name,
        width=width,
        height=height,
    )


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
        scene_path = settings.artifact_dir / "scenes" / model_revision / "canonical_scene.json"
        if not scene_path.is_file() and settings.aps_configured:
            await run_in_threadpool(_prepare_uploaded_model, target, settings)
    except InvalidModelError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except V365Error as exc:
        raise HTTPException(
            status_code=502,
            detail=f"APS model preparation failed: {exc}",
        ) from exc
    finally:
        temporary.unlink(missing_ok=True)

    ready = (settings.artifact_dir / "scenes" / model_revision / "canonical_scene.json").is_file()
    return ModelUploadResponse(
        model_revision=model_revision,
        file_name=file_name,
        size_bytes=size_bytes,
        ready=ready,
    )


@app.get(
    "/v1/models/{model_revision}/design-capabilities",
    response_model=ModelDesignCapabilities,
    tags=["models"],
)
def model_design_capabilities(model_revision: str) -> ModelDesignCapabilities:
    _require_safe_identifier(model_revision, "model_revision")
    scene_path = _settings().artifact_dir / "scenes" / model_revision / "canonical_scene.json"
    if not scene_path.is_file():
        raise HTTPException(status_code=404, detail="canonical scene not found")
    scene = CanonicalScene.model_validate_json(scene_path.read_text(encoding="utf-8"))
    return AnalyzeModelDesignCapabilities().execute(model_revision, scene)


@app.post(
    "/v1/models/{model_revision}/design-preview",
    response_model=DesignPreviewResponse,
    tags=["design"],
)
def preview_design(
    model_revision: str,
    request: DesignPreviewRequest,
) -> DesignPreviewResponse:
    _require_safe_identifier(model_revision, "model_revision")
    scene_path = _settings().artifact_dir / "scenes" / model_revision / "canonical_scene.json"
    if not scene_path.is_file():
        raise HTTPException(status_code=404, detail="canonical scene not found")
    scene = CanonicalScene.model_validate_json(scene_path.read_text(encoding="utf-8"))
    capabilities = AnalyzeModelDesignCapabilities().execute(model_revision, scene)
    compiled = CompileUserRenderIntent().execute(
        request.project_id,
        request.intent,
        capabilities,
    )
    design_revision = PlanDesign.revision(scene, compiled.brief)
    return DesignPreviewResponse(
        model_revision=model_revision,
        preview_token=_preview_token(
            model_revision,
            request.project_id,
            compiled.normalized_intent,
        ),
        normalized_intent=compiled.normalized_intent,
        capabilities=capabilities,
        industrial_context=PlanIndustrialContext().execute(
            scene, design_revision, compiled.brief.site_design
        ),
        warnings=compiled.warnings,
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
    if request.brief is not None and request.brief.project_id != project_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="brief project_id must match the route project_id",
        )
    settings = _settings()
    scene_path = settings.artifact_dir / "scenes" / request.model_revision / "canonical_scene.json"
    if not scene_path.is_file():
        raise HTTPException(status_code=404, detail="canonical scene not found")
    scene = CanonicalScene.model_validate_json(scene_path.read_text(encoding="utf-8"))
    capabilities = AnalyzeModelDesignCapabilities().execute(request.model_revision, scene)
    compiled = (
        CompileUserRenderIntent().execute(project_id, request.intent, capabilities)
        if request.intent is not None
        else None
    )
    if compiled is not None and request.preview_token is not None:
        expected_preview_token = _preview_token(
            request.model_revision,
            project_id,
            compiled.normalized_intent,
        )
        if request.preview_token != expected_preview_token:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="design inputs changed after preview; run design preview again",
            )
    brief = compiled.brief if compiled is not None else request.brief
    if brief is None:  # Defended by request validation; keeps the type boundary explicit.
        raise HTTPException(status_code=422, detail="design input is missing")
    revision = PlanDesign.revision(scene, brief)
    target = _design_directory(settings.artifact_dir, request.model_revision, revision)
    brief_path = target / "design_brief.json"
    atomic_write(brief_path, brief.model_dump_json(indent=2).encode() + b"\n")
    if compiled is not None:
        atomic_write(
            target / "render_intent.json",
            compiled.normalized_intent.model_dump_json(indent=2).encode() + b"\n",
        )
        atomic_write(
            target / "intent_compilation.json",
            json.dumps(
                {
                    "catalog_version": compiled.catalog_version,
                    "warnings": [item.model_dump() for item in compiled.warnings],
                },
                ensure_ascii=False,
                indent=2,
            ).encode("utf-8")
            + b"\n",
        )
    design = PlanDesign().execute(scene_path, brief_path)
    return DesignRevisionResponse(
        project_id=project_id,
        model_revision=request.model_revision,
        design_revision=design.design_revision,
        design_dna_ref=str(target / "design_dna.json"),
        brief_ref=str(brief_path),
        normalized_intent=(compiled.normalized_intent if compiled is not None else None),
        warnings=compiled.warnings if compiled is not None else (),
        preset_catalog_version=compiled.catalog_version if compiled is not None else None,
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
    reference_refs, reference_roles = _resolve_references(
        settings.artifact_dir, request.reference_ids
    )
    reference_refs, reference_roles = _with_active_quality_baseline(
        settings.artifact_dir, reference_refs, reference_roles
    )
    required_reference_roles = {
        "factory_design_reference",
        "context_realism_reference",
    }
    if (
        request.profile is not GenerationProfile.PREVIEW_FAST
        and not required_reference_roles.issubset(reference_roles)
    ):
        missing = sorted(required_reference_roles - set(reference_roles))
        raise HTTPException(
            status_code=422,
            detail=("tender generation requires approved reference roles: " + ", ".join(missing)),
        )
    created = CreateGenerationJob().execute(
        _repository(settings),
        project_id=design.project_id,
        model_revision=request.model_revision,
        design_revision=design_revision,
        view_set=view_set,
        profile=request.profile,
        render_profile=request.render_profile,
        image_provider=settings.image_provider,
        reference_image_refs=reference_refs,
        reference_roles=reference_roles,
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
        WorkflowState.HUMAN_REVIEW,
        WorkflowState.DESIGN_MASTER_REVIEW,
    }:
        _generation_dispatcher.submit(job.job_id)
    return ViewSetJobResponse(
        job_id=job.job_id,
        trace_id=job.trace_id,
        view_set_id=job.view_set_id,
        design_revision=job.design_revision,
        state=job.state,
        certification_state=_certification_state(job, settings),
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
    settings = _settings()
    try:
        job = _repository(settings).get_by_view_set(view_set_id)
    except OSError as exc:
        raise HTTPException(status_code=404, detail="view set not found") from exc
    return ViewSetJobResponse(
        job_id=job.job_id,
        trace_id=job.trace_id,
        view_set_id=job.view_set_id,
        design_revision=job.design_revision,
        state=job.state,
        certification_state=_certification_state(job, settings),
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


@app.post(
    "/v1/view-sets/{view_set_id}/video-jobs",
    response_model=VideoJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["video"],
)
def create_video_job(view_set_id: str) -> VideoJobResponse:
    """Start video generation only after an explicit request for a completed image set."""

    _require_safe_identifier(view_set_id, "view_set_id")
    settings = _settings()
    try:
        image_job = _repository(settings).get_by_view_set(view_set_id)
    except OSError as exc:
        raise HTTPException(status_code=404, detail="view set not found") from exc
    if image_job.state is not WorkflowState.COMPLETED:
        raise HTTPException(
            status_code=409,
            detail="the image view set must complete before video generation",
        )

    generated_root = (
        settings.artifact_dir / "generated" / image_job.model_revision / image_job.design_revision
    )
    manifest = generated_root / "viewset_generation_manifest.json"
    board = generated_root / "viewset_board.jpg"
    view_set_path = (
        settings.artifact_dir
        / "scenes"
        / image_job.model_revision
        / "designs"
        / image_job.design_revision
        / "view_set.json"
    )
    try:
        view_set = ViewSet.model_validate_json(view_set_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise HTTPException(
            status_code=409,
            detail="the completed image set has no valid camera set",
        ) from exc
    source_images_ready = all(
        len(tuple((generated_root / camera.view_id).glob("provider_source.*"))) == 1
        or (generated_root / camera.view_id / "refined.jpg").is_file()
        for camera in view_set.cameras
    )
    if not manifest.is_file() or not board.is_file() or not source_images_ready:
        raise HTTPException(
            status_code=409,
            detail="the completed image set is missing approved generation artifacts",
        )

    created = CreateVideoJob().execute(
        _video_repository(settings),
        image_job,
        settings,
        shot_count=len(view_set.cameras),
    )
    job = created.job
    if settings.local_worker_enabled and job.state not in {
        VideoJobState.COMPLETED,
        VideoJobState.FAILED,
    }:
        _video_dispatcher.submit(job.video_job_id)
    return _video_job_response(job, created=created.created)


@app.get(
    "/v1/video-jobs/{video_job_id}",
    response_model=VideoJobResponse,
    tags=["video"],
)
def get_video_job(video_job_id: str) -> VideoJobResponse:
    _require_safe_identifier(video_job_id, "video_job_id")
    try:
        job = _video_repository(_settings()).get(video_job_id)
    except OSError as exc:
        raise HTTPException(status_code=404, detail="video job not found") from exc
    return _video_job_response(job, created=False)


@app.get(
    "/v1/video-jobs/{video_job_id}/output",
    response_class=FileResponse,
    tags=["video"],
)
def download_video_job_output(video_job_id: str) -> FileResponse:
    _require_safe_identifier(video_job_id, "video_job_id")
    try:
        job = _video_repository(_settings()).get(video_job_id)
    except OSError as exc:
        raise HTTPException(status_code=404, detail="video job not found") from exc
    if job.state is not VideoJobState.COMPLETED or not job.output_ref:
        raise HTTPException(status_code=409, detail="video is not completed")
    output = Path(job.output_ref).resolve()
    videos_root = (_settings().artifact_dir / "videos").resolve()
    if not output.is_relative_to(videos_root):
        raise HTTPException(status_code=409, detail="invalid video artifact reference")
    if not output.is_file():
        raise HTTPException(status_code=404, detail="video artifact not found")
    return FileResponse(output, filename=output.name, media_type="video/mp4")


def _transition_view_set(view_set_id: str, target: WorkflowState) -> ViewSetJobResponse:
    settings = _settings()
    repository = _repository(settings)
    try:
        job = repository.get_by_view_set(view_set_id)
        updated = job.transition(target)
    except OSError as exc:
        raise HTTPException(status_code=404, detail="view set not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    repository.save(updated)
    if settings.local_worker_enabled and updated.state not in {
        WorkflowState.COMPLETED,
        WorkflowState.FAILED,
        WorkflowState.HUMAN_REVIEW,
        WorkflowState.DESIGN_MASTER_REVIEW,
    }:
        _generation_dispatcher.submit(updated.job_id)
    return ViewSetJobResponse(
        job_id=updated.job_id,
        trace_id=updated.trace_id,
        view_set_id=updated.view_set_id,
        design_revision=updated.design_revision,
        state=updated.state,
        certification_state=_certification_state(updated, settings),
        created=False,
        error_code=updated.error_code,
        error_message=updated.error_message,
    )


@app.post(
    "/v1/view-sets/{view_set_id}/approve",
    response_model=ViewSetJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["review"],
)
def approve_view_set(view_set_id: str) -> ViewSetJobResponse:
    """Approve either the Design Master checkpoint or the complete reviewed image set."""

    _require_safe_identifier(view_set_id, "view_set_id")
    settings = _settings()
    try:
        job = _repository(settings).get_by_view_set(view_set_id)
    except OSError as exc:
        raise HTTPException(status_code=404, detail="view set not found") from exc
    if job.state is WorkflowState.DESIGN_MASTER_REVIEW:
        review_path = (
            settings.artifact_dir
            / "generated"
            / job.model_revision
            / job.design_revision
            / "design_master_review.json"
        )
        try:
            review = json.loads(review_path.read_text(encoding="utf-8"))
            if review.get("view_set_id") not in {None, job.view_set_id}:
                raise ValueError("Design Master belongs to a different view set")
            if not review.get("master_image_ref") or not Path(review["master_image_ref"]).is_file():
                raise ValueError("Design Master image is missing")
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        review.update({"approved": True, "status": "approved"})
        atomic_write(
            review_path,
            json.dumps(review, ensure_ascii=False, indent=2).encode("utf-8") + b"\n",
        )
        return _transition_view_set(view_set_id, WorkflowState.GENERATING_VIEWSET)
    if job.state is WorkflowState.HUMAN_REVIEW:
        qa_path = (
            settings.artifact_dir
            / "generated"
            / job.model_revision
            / job.design_revision
            / "technical_qa.json"
        )
        try:
            qa = json.loads(qa_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=409, detail="technical QA evidence is missing") from exc
        if not qa.get("passed", False):
            raise HTTPException(
                status_code=409,
                detail=(
                    "Không thể hoàn tất: bộ ảnh còn hard QA failure. Hãy sửa hoặc tạo lại "
                    "các view lỗi trước khi duyệt bàn giao."
                ),
            )
        atomic_write(
            qa_path.parent / "final_viewset_review.json",
            json.dumps(
                {
                    "schema_version": "1.0.0",
                    "status": "approved",
                    "approved": True,
                    "view_set_id": job.view_set_id,
                    "technical_qa_sha256": hashlib.sha256(qa_path.read_bytes()).hexdigest(),
                },
                ensure_ascii=False,
                indent=2,
            ).encode("utf-8")
            + b"\n",
        )
    return _transition_view_set(view_set_id, WorkflowState.COMPOSING_BOARD)


@app.post(
    "/v1/view-sets/{view_set_id}/masters/reject",
    response_model=ViewSetJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["review"],
)
def reject_design_master(
    view_set_id: str,
    scope: Literal["all", "facade"] = "all",
) -> ViewSetJobResponse:
    """Reject the current master and regenerate it without rerunning upstream geometry."""

    _require_safe_identifier(view_set_id, "view_set_id")
    settings = _settings()
    try:
        job = _repository(settings).get_by_view_set(view_set_id)
    except OSError as exc:
        raise HTTPException(status_code=404, detail="view set not found") from exc
    if job.state not in {WorkflowState.DESIGN_MASTER_REVIEW, WorkflowState.HUMAN_REVIEW}:
        raise HTTPException(
            status_code=409,
            detail="only a pending Design Master or final visual review can be rejected",
        )
    review_path = (
        settings.artifact_dir
        / "generated"
        / job.model_revision
        / job.design_revision
        / "design_master_review.json"
    )
    try:
        review = json.loads(review_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=409, detail="Design Master review evidence is missing"
        ) from exc
    review.update(
        {
            "approved": False,
            "status": f"{scope}_rejected",
            "approved_master_types": ["site"] if scope == "facade" else [],
        }
    )
    atomic_write(
        review_path,
        json.dumps(review, ensure_ascii=False, indent=2).encode("utf-8") + b"\n",
    )
    return _transition_view_set(view_set_id, WorkflowState.GENERATING_VIEWSET)


@app.post(
    "/v1/view-sets/{view_set_id}/retry",
    response_model=ViewSetJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["review"],
)
def retry_view_set(view_set_id: str) -> ViewSetJobResponse:
    """Explicitly resume a failed job from its cheapest valid checkpoint."""

    _require_safe_identifier(view_set_id, "view_set_id")
    settings = _settings()
    try:
        job = _repository(settings).get_by_view_set(view_set_id)
    except OSError as exc:
        raise HTTPException(status_code=404, detail="view set not found") from exc
    if job.state is not WorkflowState.FAILED:
        raise HTTPException(status_code=409, detail="only failed jobs can be retried")
    generated_root = settings.artifact_dir / "generated" / job.model_revision / job.design_revision
    review_path = generated_root / "design_master_review.json"
    try:
        review = json.loads(review_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        review = {}
    if review.get("approved", False):
        view_set_path = (
            settings.artifact_dir
            / "scenes"
            / job.model_revision
            / "designs"
            / job.design_revision
            / "view_set.json"
        )
        try:
            view_set = ViewSet.model_validate_json(view_set_path.read_text(encoding="utf-8"))
            complete_outputs = all(
                any((generated_root / camera.view_id).glob("refined.*"))
                for camera in view_set.cameras
            )
        except (OSError, ValueError):
            complete_outputs = False
        # FAILED resumes through a legal checkpoint. Valid conditioning is reused there before
        # the worker advances to the approved-master generation branch.
        target = WorkflowState.VALIDATING if complete_outputs else WorkflowState.RENDERING_PASSES
    else:
        target = (
            WorkflowState.VALIDATING
            if (generated_root / "viewset_generation_manifest.json").is_file()
            and (generated_root / "protected_composite_manifest.json").is_file()
            else WorkflowState.RENDERING_PASSES
        )
    return _transition_view_set(view_set_id, target)


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


# -- view edits ----------------------------------------------------------
#
# An edit belongs to a view *within one view set*: `view-03` exists in every
# view set, so these paths carry both ids rather than the view id alone.


@contextmanager
def _edit_errors() -> Iterator[None]:
    """One mapping from an edit's refusals to the status the browser sees.

    A refusal here is about what was asked — the wrong state, a spent repair
    budget, a mask that selects nothing — so it answers 409 rather than 500. A
    provider that fails is the service's own failure and answers 502.
    """

    try:
        yield
    except (ConfigurationError, InvalidModelError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


def _job_for_edit(view_set_id: str, view_id: str) -> GenerationJob:
    _require_safe_identifier(view_set_id, "view_set_id")
    _require_safe_identifier(view_id, "view_id")
    try:
        return _repository(_settings()).get_by_view_set(view_set_id)
    except OSError as exc:
        raise HTTPException(status_code=404, detail="view set not found") from exc


def _edit_store(job: GenerationJob, view_id: str) -> ViewEditStore:
    return ViewEditStore(view_directory(_settings(), job, view_id))


def _edit_response(record: ViewEditRecord, view_set_id: str) -> ViewEditResponse:
    base = f"/v1/view-sets/{view_set_id}/views/{record.view_id}/edits/{record.edit_id}"
    return ViewEditResponse(
        edit_id=record.edit_id,
        view_id=record.view_id,
        sequence=record.sequence,
        kind=record.kind,
        state=record.state,
        prompt=record.prompt,
        candidate_count=record.candidate_count,
        chosen=record.chosen,
        created_by=record.created_by,
        created_at=record.created_at,
        committed_at=record.committed_at,
        previous_url=f"{base}/image?variant=previous",
        candidate_urls=tuple(
            f"{base}/image?variant=candidate&index={index}"
            for index in range(record.candidate_count)
        ),
    )


async def _read_upload(upload: UploadFile, label: str) -> bytes:
    content = await upload.read()
    if len(content) > MAX_REFERENCE_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"{label} exceeds {MAX_REFERENCE_UPLOAD_BYTES} bytes",
        )
    return content


@app.post(
    "/v1/view-sets/{view_set_id}/views/{view_id}/edits",
    response_model=StartViewEditResponse,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["review"],
)
async def start_view_edit(
    view_set_id: str,
    view_id: str,
    prompt: str = Form(...),
    created_by: str = _EDIT_USER_HEADER,
    quality: str | None = Form(None),
    size: str | None = Form(None),
    candidates: int = Form(1),
    mask: UploadFile | None = _MASK_FILE,
    references: list[UploadFile] | None = _REFERENCE_FILES,
) -> StartViewEditResponse:
    with _edit_errors():
        job = _job_for_edit(view_set_id, view_id)
    if len(references or ()) > MAX_REFERENCES:
        raise HTTPException(
            status_code=422,
            detail=f"an edit takes at most {MAX_REFERENCES} reference images",
        )
    settings = _settings()
    mask_bytes = await _read_upload(mask, "mask") if mask is not None else None
    reference_paths: list[Path] = []
    scratch = settings.artifact_dir / "edit_uploads" / uuid.uuid4().hex
    for index, upload in enumerate(references or ()):
        content = await _read_upload(upload, "reference image")
        suffix = Path(upload.filename or f"reference-{index}.png").suffix or ".png"
        target = scratch / f"{index:02d}{suffix}"
        atomic_write(target, content)
        reference_paths.append(target)

    edit_id = uuid.uuid4().hex

    def work(publish: Publish) -> None:
        publish("started", {"edit_id": edit_id, "view_id": view_id})

        def on_partial(index: int, content: bytes) -> None:
            publish(
                "partial_image",
                {"index": index, "b64_png": base64.b64encode(content).decode("ascii")},
            )

        try:
            applied = ApplyViewEdit().execute(
                settings=settings,
                repository=_repository(settings),
                job=job,
                view_id=view_id,
                edit_id=edit_id,
                prompt=prompt,
                mask=mask_bytes,
                references=tuple(reference_paths),
                quality=quality,
                size=size,
                candidates=candidates,
                created_by=created_by,
                on_partial=on_partial,
            )
        finally:
            for path in reference_paths:
                path.unlink(missing_ok=True)
        publish(
            "completed",
            {"edit": _edit_response(applied.record, view_set_id).model_dump(mode="json")},
        )
        if applied.requeued and settings.local_worker_enabled:
            publish("validating", {"view_set_id": view_set_id})
            _generation_dispatcher.submit(applied.job.job_id)

    _edit_dispatcher.start(edit_id, work)
    return StartViewEditResponse(edit_id=edit_id, view_id=view_id, view_set_id=view_set_id)


@app.get(
    "/v1/view-sets/{view_set_id}/views/{view_id}/edits/{edit_id}/events",
    tags=["review"],
)
def stream_view_edit(view_set_id: str, view_id: str, edit_id: str) -> StreamingResponse:
    _require_safe_identifier(view_set_id, "view_set_id")
    _require_safe_identifier(view_id, "view_id")
    _require_safe_identifier(edit_id, "edit_id")
    stream = _edit_dispatcher.stream(edit_id)
    if stream is None:
        raise HTTPException(status_code=404, detail="edit run is no longer available")
    return StreamingResponse(
        stream.read(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get(
    "/v1/view-sets/{view_set_id}/views/{view_id}/edits",
    response_model=ViewEditListResponse,
    tags=["review"],
)
def list_view_edits(view_set_id: str, view_id: str) -> ViewEditListResponse:
    with _edit_errors():
        job = _job_for_edit(view_set_id, view_id)
        store = _edit_store(job, view_id)
        return ViewEditListResponse(
            edits=tuple(_edit_response(record, view_set_id) for record in store.records()),
            attempt=job.attempt,
            editable=job.state in EDITABLE_STATES and job.attempt < 3,
        )


@app.get(
    "/v1/view-sets/{view_set_id}/views/{view_id}/edits/{edit_id}/image",
    response_class=FileResponse,
    tags=["review"],
)
def download_view_edit_image(
    view_set_id: str,
    view_id: str,
    edit_id: str,
    variant: Literal["previous", "candidate"] = "previous",
    index: int = 0,
) -> FileResponse:
    _require_safe_identifier(edit_id, "edit_id")
    with _edit_errors():
        job = _job_for_edit(view_set_id, view_id)
        store = _edit_store(job, view_id)
        record = store.record(edit_id)
        path = (
            store.previous_image(record)
            if variant == "previous"
            else store.candidate_image(record, index)
        )
        return FileResponse(path, media_type=media_type_of(path), filename=path.name)


@app.post(
    "/v1/view-sets/{view_set_id}/views/{view_id}/edits/{edit_id}/commit",
    response_model=ViewEditResponse,
    tags=["review"],
)
def commit_view_edit(
    view_set_id: str,
    view_id: str,
    edit_id: str,
    request: CommitViewEditRequest,
) -> ViewEditResponse:
    _require_safe_identifier(edit_id, "edit_id")
    with _edit_errors():
        job = _job_for_edit(view_set_id, view_id)
        settings = _settings()
        applied = CommitViewEdit().execute(
            settings=settings,
            repository=_repository(settings),
            job=job,
            view_id=view_id,
            edit_id=edit_id,
            chosen=request.chosen,
        )
        if settings.local_worker_enabled:
            _generation_dispatcher.submit(applied.job.job_id)
        return _edit_response(applied.record, view_set_id)


@app.post(
    "/v1/view-sets/{view_set_id}/views/{view_id}/edits/{edit_id}/restore",
    response_model=ViewEditResponse,
    tags=["review"],
)
def restore_view_edit(
    view_set_id: str,
    view_id: str,
    edit_id: str,
    request: RestoreViewEditRequest,
) -> ViewEditResponse:
    _require_safe_identifier(edit_id, "edit_id")
    with _edit_errors():
        job = _job_for_edit(view_set_id, view_id)
        settings = _settings()
        applied = RestoreViewEdit().execute(
            settings=settings,
            repository=_repository(settings),
            job=job,
            view_id=view_id,
            source_edit_id=edit_id,
            edit_id=uuid.uuid4().hex,
            created_by=request.created_by,
        )
        if settings.local_worker_enabled:
            _generation_dispatcher.submit(applied.job.job_id)
        return _edit_response(applied.record, view_set_id)
