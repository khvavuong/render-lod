"""Provider ports used by the application layer."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from v365_archviz.domain.jobs import GenerationJob
from v365_archviz.domain.scene import CanonicalScene, SourceModelRef


@dataclass(frozen=True)
class GeometryExtractionRequest:
    source: SourceModelRef
    working_directory: Path


class GeometryProvider(Protocol):
    """Normalize an exact model version into the canonical scene contract."""

    @property
    def name(self) -> str: ...

    def extract(self, request: GeometryExtractionRequest) -> CanonicalScene: ...


@dataclass(frozen=True)
class ViewConditioningInput:
    view_id: str
    base_rgb: Path
    depth: Path
    instance_id: Path
    semantic: Path
    edges: Path
    prompt: str
    structure_guide: Path | None = None
    reference_images: tuple[Path, ...] = ()
    aspect_ratio: str = "16:9"
    image_size: str = "1K"


@dataclass(frozen=True)
class GeneratedImage:
    content: bytes
    media_type: str
    provider_request_id: str | None


@dataclass(frozen=True)
class ImageProviderCapabilities:
    supports_masked_edit: bool = False
    supports_control_image: bool = False
    supports_control_scale: bool = False
    supports_edit_strength: bool = False
    supports_seed: bool = False
    supports_multi_reference: bool = False
    supports_multi_turn_state: bool = False


@dataclass(frozen=True)
class ViewSetGenerationInput:
    request_id: str
    project_id: str
    model_revision: str
    design_revision: str
    view_set_id: str
    profile: str
    views: tuple[ViewConditioningInput, ...]


@dataclass(frozen=True)
class GeneratedView:
    view_id: str
    image: GeneratedImage


@dataclass(frozen=True)
class GeneratedViewSet:
    request_id: str
    views: tuple[GeneratedView, ...]


class GenerativeRenderer(Protocol):
    """Render one view without owning or changing the shared design state."""

    @property
    def name(self) -> str: ...

    @property
    def capabilities(self) -> ImageProviderCapabilities: ...

    def generate(self, request: ViewConditioningInput) -> GeneratedImage: ...


class ViewSetGenerativeRenderer(GenerativeRenderer, Protocol):
    """Generate one ordered, revision-bound view set as the core provider operation."""

    def generate_view_set(self, request: ViewSetGenerationInput) -> GeneratedViewSet: ...


@dataclass(frozen=True)
class VideoGenerationInput:
    shot_id: str
    source_image: Path
    prompt: str
    negative_prompt: str
    duration_seconds: int
    aspect_ratio: str
    resolution: str
    seed: int


@dataclass(frozen=True)
class VideoOperation:
    name: str
    done: bool = False
    download_uri: str | None = None
    error_message: str | None = None


class VideoGenerationProvider(Protocol):
    """Start, resume and download one asynchronous image-to-video operation."""

    @property
    def name(self) -> str: ...

    def start(self, request: VideoGenerationInput) -> VideoOperation: ...

    def get(self, operation_name: str) -> VideoOperation: ...

    def download(self, operation: VideoOperation) -> bytes: ...


class JobRepository(Protocol):
    """Durable metadata port; adapters may use local files or a database."""

    def create_or_get(self, job: GenerationJob) -> tuple[GenerationJob, bool]: ...

    def get(self, job_id: str) -> GenerationJob: ...

    def get_by_view_set(self, view_set_id: str) -> GenerationJob: ...

    def save(self, job: GenerationJob) -> None: ...
