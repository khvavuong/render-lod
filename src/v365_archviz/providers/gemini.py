"""Gemini image-generation adapter with privacy-safe defaults."""

from __future__ import annotations

import base64
import mimetypes
from pathlib import Path
from typing import Any

import httpx
from PIL import Image, UnidentifiedImageError

from v365_archviz.config import Settings
from v365_archviz.errors import ConfigurationError, ProviderError
from v365_archviz.providers.contracts import (
    GeneratedImage,
    GeneratedView,
    GeneratedViewSet,
    ViewConditioningInput,
    ViewSetGenerationInput,
)

DEFAULT_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/interactions"


def _image_block(path: Path) -> dict[str, str]:
    if not path.is_file():
        raise ProviderError(f"conditioning image does not exist: {path}")
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    try:
        with Image.open(path) as image:
            if image.format:
                media_type = Image.MIME.get(image.format, media_type)
    except (UnidentifiedImageError, OSError):
        pass
    if not media_type.startswith("image/"):
        raise ProviderError(f"conditioning artifact is not an image: {path}")
    return {
        "type": "image",
        "mime_type": media_type,
        "data": base64.b64encode(path.read_bytes()).decode("ascii"),
    }


def _find_output_image(value: Any) -> tuple[bytes, str] | None:
    if isinstance(value, dict):
        data = value.get("data")
        media_type = value.get("mime_type") or value.get("mimeType")
        if (
            isinstance(data, str)
            and isinstance(media_type, str)
            and media_type.startswith("image/")
        ):
            try:
                return base64.b64decode(data, validate=True), media_type
            except ValueError as exc:
                raise ProviderError("Gemini returned invalid base64 image data") from exc
        for child in value.values():
            found = _find_output_image(child)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _find_output_image(child)
            if found:
                return found
    return None


class GeminiImageRenderer:
    name = "gemini"

    def __init__(
        self,
        settings: Settings,
        *,
        client: httpx.Client | None = None,
        endpoint: str = DEFAULT_ENDPOINT,
    ) -> None:
        api_key = settings.gemini_api_key
        if not api_key:
            raise ConfigurationError("GEMINI_API_KEY is required for Gemini generation")
        self._settings = settings
        self._api_key = api_key
        self._client = client or httpx.Client(timeout=httpx.Timeout(180.0, connect=10.0))
        self._owns_client = client is None
        self._endpoint = endpoint

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> GeminiImageRenderer:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def generate(self, request: ViewConditioningInput) -> GeneratedImage:
        labeled_prompt = (
            f"{request.prompt}\n\n"
            "The attached images are ordered as: base RGB, depth, instance ID, semantic ID, "
            "edges, "
            "then optional approved references. Preserve the camera and all hard geometry "
            "from the base RGB; auxiliary passes are constraints. Approved references are "
            "non-binding realism samples only: use their photographic credibility, material "
            "response and construction-detail density. Do not copy their palette, facade motif, "
            "roof form, massing, site or landscape layout, surrounding land use, camera, logos, "
            "labels, text, or project-specific objects. Semantic-ID legend: red = focus factory "
            "shed, "
            "blue = focus office, bright green = authored landscape zone, charcoal = road, "
            "warm grey = sidewalk, cyan = authored roof, muted grey = context building. "
            "Respect every semantic boundary exactly. A context building may be drawn only over "
            "muted-grey context pixels; grey background is empty space, not permission to invent "
            "massing."
        )
        paths = (
            request.base_rgb,
            request.depth,
            request.instance_id,
            request.semantic,
            request.edges,
            *request.reference_images,
        )
        payload = {
            "model": self._settings.gemini_image_model,
            "input": [{"type": "text", "text": labeled_prompt}, *map(_image_block, paths)],
            "store": self._settings.gemini_store_interactions,
            "generation_config": {
                "image_config": {
                    "aspect_ratio": request.aspect_ratio,
                    "image_size": request.image_size,
                }
            },
        }

        try:
            response = self._client.post(
                self._endpoint,
                json=payload,
                headers={"x-goog-api-key": self._api_key},
            )
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
            suffix = f" (HTTP {status})" if status else ""
            raise ProviderError(f"Gemini request failed{suffix}") from exc

        output = _find_output_image(body)
        if output is None:
            raise ProviderError("Gemini response did not contain an output image")
        content, media_type = output
        request_id = body.get("id") if isinstance(body, dict) else None
        return GeneratedImage(
            content=content,
            media_type=media_type,
            provider_request_id=request_id if isinstance(request_id, str) else None,
        )

    def generate_view_set(self, request: ViewSetGenerationInput) -> GeneratedViewSet:
        """Execute the ordered unit sequentially behind the provider-neutral view-set port."""

        views = tuple(
            GeneratedView(view_id=view.view_id, image=self.generate(view)) for view in request.views
        )
        return GeneratedViewSet(request_id=request.request_id, views=views)
