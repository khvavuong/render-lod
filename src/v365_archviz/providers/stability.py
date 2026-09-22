"""Stability Control Structure adapter for geometry-conditioned beauty generation."""

from __future__ import annotations

import hashlib
import mimetypes
from collections.abc import Callable

import httpx

from v365_archviz.config import Settings
from v365_archviz.errors import ConfigurationError, ProviderError
from v365_archviz.providers.contracts import (
    GeneratedImage,
    GeneratedView,
    GeneratedViewSet,
    ImageProviderCapabilities,
    ViewConditioningInput,
    ViewEditInput,
    ViewSetGenerationInput,
)

DEFAULT_ENDPOINT = "https://api.stability.ai/v2beta/stable-image/control/structure"
NEGATIVE_PROMPT = (
    "CGI, 3D render, illustration, miniature, tilt shift, plastic vegetation, repeated trees, "
    "fantasy architecture, changed massing, changed roof, flat roof, invented building, "
    "missing road, blocked gate, warped facade, text, logo, watermark, oversaturated colors"
)


class StabilityStructureRenderer:
    """Generate photoreal beauty while preserving a control render's structure."""

    name = "stability-control-structure"
    capabilities = ImageProviderCapabilities(
        supports_control_image=True,
        supports_control_scale=True,
        supports_seed=True,
    )

    def __init__(
        self,
        settings: Settings,
        *,
        client: httpx.Client | None = None,
        endpoint: str = DEFAULT_ENDPOINT,
    ) -> None:
        if not settings.stability_api_key:
            raise ConfigurationError(
                "STABILITY_API_KEY is required for Stability Control Structure"
            )
        if not 0.0 <= settings.stability_control_strength <= 1.0:
            raise ConfigurationError("STABILITY_CONTROL_STRENGTH must be between 0 and 1")
        if not 0 <= settings.stability_seed <= 4_294_967_294:
            raise ConfigurationError("STABILITY_SEED must be between 0 and 4294967294")
        self._api_key = settings.stability_api_key
        self._control_strength = settings.stability_control_strength
        self._base_seed = settings.stability_seed
        self._client = client or httpx.Client(timeout=httpx.Timeout(180.0, connect=10.0))
        self._owns_client = client is None
        self._endpoint = endpoint

    @property
    def provenance(self) -> dict[str, object]:
        return {
            "endpoint_family": "stable-image/control/structure",
            "control_strength": self._control_strength,
            "base_seed": self._base_seed,
            "output_format": "jpeg",
            "style_preset": "photographic",
        }

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> StabilityStructureRenderer:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _seed_for(self, view_id: str) -> int:
        offset = int.from_bytes(hashlib.sha256(view_id.encode()).digest()[:4], "big")
        return (self._base_seed + offset) % 4_294_967_295

    def generate(self, request: ViewConditioningInput) -> GeneratedImage:
        control_image = request.structure_guide or request.base_rgb
        if not control_image.is_file():
            raise ProviderError(f"control image does not exist: {control_image}")
        media_type = mimetypes.guess_type(control_image.name)[0] or "image/png"
        files = {
            "image": (
                control_image.name,
                control_image.read_bytes(),
                media_type,
            )
        }
        data = {
            "prompt": request.prompt,
            "negative_prompt": NEGATIVE_PROMPT,
            "control_strength": str(self._control_strength),
            "seed": str(self._seed_for(request.view_id)),
            "output_format": "jpeg",
            "style_preset": "photographic",
        }
        try:
            response = self._client.post(
                self._endpoint,
                headers={
                    "authorization": f"Bearer {self._api_key}",
                    "accept": "image/*",
                    "stability-client-id": "v365-archviz",
                    "stability-client-version": "1.0",
                },
                files=files,
                data=data,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
            suffix = f" (HTTP {status})" if status else ""
            raise ProviderError(f"Stability Control Structure request failed{suffix}") from exc
        media_type = response.headers.get("content-type", "image/jpeg").split(";", 1)[0]
        if not media_type.startswith("image/") or not response.content:
            raise ProviderError("Stability returned an invalid image response")
        request_id = response.headers.get("stability-request-id")
        return GeneratedImage(response.content, media_type, request_id)

    def edit(
        self,
        request: ViewEditInput,
        *,
        on_partial: Callable[[int, bytes], None] | None = None,
    ) -> tuple[GeneratedImage, ...]:
        raise ProviderError(
            "Stability cannot repaint a masked region; set OPENAI_API_KEY so view edits "
            "run through the OpenAI images/edits endpoint"
        )

    def generate_view_set(self, request: ViewSetGenerationInput) -> GeneratedViewSet:
        views = tuple(
            GeneratedView(view_id=view.view_id, image=self.generate(view)) for view in request.views
        )
        return GeneratedViewSet(request_id=request.request_id, views=views)
