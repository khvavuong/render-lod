"""Provider ports used by the application layer."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

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
class ViewEditInput:
    """One human-directed edit of a view that already has a refined image.

    `mask` is a PNG whose transparent pixels are the region the provider may
    change; every opaque pixel must come back untouched. That is the convention
    the OpenAI edits endpoint reads, and the mask the browser draws.
    """

    view_id: str
    base_image: Path
    prompt: str
    mask: bytes | None = None
    reference_images: tuple[Path, ...] = ()
    #: What the references are for. `realism` borrows photographic credibility
    #: and nothing else. `change` says the reference is this same project after
    #: an approved edit, and is the authority for what changed — which is how
    #: one view's edit is carried across to the other five.
    reference_intent: Literal["realism", "change"] = "realism"
    aspect_ratio: str = "16:9"
    quality: str | None = None
    size: str | None = None
    candidates: int = 1


@dataclass(frozen=True)
class ViewSetGenerationInput:
    request_id: str
    project_id: str
    model_revision: str
    design_revision: str
    view_set_id: str
    profile: str
    views: tuple[ViewConditioningInput, ...]
    identity_prompt: str = ""
    master_view_id: str = "view-01"
    design_master: GeneratedImage | None = None


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

    def edit(
        self,
        request: ViewEditInput,
        *,
        on_partial: Callable[[int, bytes], None] | None = None,
    ) -> tuple[GeneratedImage, ...]:
        """Redraw the masked region of an already refined view.

        Returns one image per requested candidate. A provider that cannot do
        this says so through `capabilities.supports_masked_edit` and raises.
        """
        ...


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
