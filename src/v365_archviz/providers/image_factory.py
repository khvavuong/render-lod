"""Central image-provider selection shared by the API worker and developer CLI."""

from __future__ import annotations

from typing import TypeAlias

from v365_archviz.config import Settings
from v365_archviz.errors import ConfigurationError
from v365_archviz.providers.gemini import GeminiConditioningMode, GeminiImageRenderer
from v365_archviz.providers.openai_image import OpenAIImageRenderer
from v365_archviz.providers.stability import StabilityStructureRenderer

ImageRenderer: TypeAlias = GeminiImageRenderer | OpenAIImageRenderer | StabilityStructureRenderer
SUPPORTED_IMAGE_PROVIDERS = ("gemini", "openai-image", "stability-structure")


def create_image_renderer(
    settings: Settings,
    provider: str | None = None,
    conditioning_mode: str | None = None,
) -> ImageRenderer:
    selected = provider or settings.image_provider
    if selected == "gemini":
        selected_mode = conditioning_mode or settings.gemini_conditioning_mode
        return GeminiImageRenderer(
            settings,
            conditioning_mode=GeminiConditioningMode(selected_mode),
        )
    if selected == "openai-image":
        return OpenAIImageRenderer(settings)
    if selected == "stability-structure":
        return StabilityStructureRenderer(settings)
    raise ConfigurationError(
        f"unsupported V365_IMAGE_PROVIDER={selected!r}; expected one of "
        f"{', '.join(SUPPORTED_IMAGE_PROVIDERS)}"
    )
