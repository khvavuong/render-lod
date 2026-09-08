"""Provider ports used by the application layer."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

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
    edges: Path
    prompt: str
    reference_images: tuple[Path, ...] = ()
    aspect_ratio: str = "16:9"
    image_size: str = "1K"


@dataclass(frozen=True)
class GeneratedImage:
    content: bytes
    media_type: str
    provider_request_id: str | None


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

    def generate(self, request: ViewConditioningInput) -> GeneratedImage: ...


class ViewSetGenerativeRenderer(GenerativeRenderer, Protocol):
    """Generate one ordered, revision-bound view set as the core provider operation."""

    def generate_view_set(self, request: ViewSetGenerationInput) -> GeneratedViewSet: ...
