"""Gemini image-generation adapter with privacy-safe defaults."""

from __future__ import annotations

import base64
import io
import mimetypes
from pathlib import Path
from typing import Any

import httpx
from PIL import Image, ImageOps, UnidentifiedImageError

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


def _generated_image_block(image: GeneratedImage) -> dict[str, str]:
    return {
        "type": "image",
        "mime_type": image.media_type,
        "data": base64.b64encode(image.content).decode("ascii"),
    }


def _neutral_semantic_block(path: Path) -> dict[str, str]:
    """Remove annotation hue while retaining every categorical boundary."""

    if not path.is_file():
        raise ProviderError(f"conditioning image does not exist: {path}")
    try:
        with Image.open(path) as source:
            neutral = ImageOps.grayscale(source).convert("RGB")
            buffer = io.BytesIO()
            neutral.save(buffer, format="PNG")
    except (UnidentifiedImageError, OSError) as exc:
        raise ProviderError(f"semantic artifact is not a readable image: {path}") from exc
    return {
        "type": "image",
        "mime_type": "image/png",
        "data": base64.b64encode(buffer.getvalue()).decode("ascii"),
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

    def _generate(
        self,
        request: ViewConditioningInput,
        style_anchor: GeneratedImage | None = None,
    ) -> GeneratedImage:
        anchor_instruction = (
            " The final attached image is a generated STYLE ANCHOR from another approved "
            "camera of this exact project. Match only its facade language, material identity, "
            "palette, daylight, atmosphere, vegetation treatment and photographic finish. "
            "Do not copy its camera, composition, object positions or geometry; the current "
            "base RGB and passes remain the sole spatial authority."
            if style_anchor is not None
            else ""
        )
        labeled_prompt = (
            f"{request.prompt}\n\n"
            "The attached images are ordered as: base RGB, depth, instance ID, semantic ID, "
            "edges, "
            "then optional approved references. Preserve the camera and all hard geometry "
            "from the base RGB; auxiliary passes are constraints. Approved references are "
            "non-binding realism samples only: use their photographic credibility, material "
            "response and construction-detail density. Do not copy their palette, facade motif, "
            "roof form, massing, site or landscape layout, surrounding land use, camera, logos, "
            "labels, text, or project-specific objects. The semantic-ID image has intentionally "
            "been converted to neutral grayscale: its tone boundaries are categorical masks, not "
            "materials, lighting or desired output colors. Use it only together with the instance, "
            "depth and edge passes to respect boundaries. No annotation tone or source semantic "
            "hue may determine a facade color in the final image. "
            "Respect every semantic boundary exactly. A context building may be drawn only over "
            "muted-grey context pixels; grey background is empty space, not permission to invent "
            f"massing.{anchor_instruction}"
        )
        input_images = [
            _image_block(request.base_rgb),
            _image_block(request.depth),
            _image_block(request.instance_id),
            _neutral_semantic_block(request.semantic),
            _image_block(request.edges),
            *map(_image_block, request.reference_images),
        ]
        input_blocks: list[dict[str, str]] = [
            {"type": "text", "text": labeled_prompt},
            *input_images,
        ]
        if style_anchor is not None:
            input_blocks.append(_generated_image_block(style_anchor))
        payload = {
            "model": self._settings.gemini_image_model,
            "input": input_blocks,
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

    def generate(self, request: ViewConditioningInput) -> GeneratedImage:
        return self._generate(request)

    def generate_view_set(self, request: ViewSetGenerationInput) -> GeneratedViewSet:
        """Generate a style-locked set for quality profiles and retain deterministic ordering."""

        if request.profile not in {"base_pro", "marketing_hero"} or len(request.views) < 2:
            views = tuple(
                GeneratedView(view_id=view.view_id, image=self.generate(view))
                for view in request.views
            )
            return GeneratedViewSet(request_id=request.request_id, views=views)

        anchor_request = next(
            (view for view in request.views if view.view_id == "view-03"), request.views[0]
        )
        anchor = self.generate(anchor_request)
        generated_by_id = {anchor_request.view_id: anchor}
        for view in request.views:
            if view.view_id != anchor_request.view_id:
                generated_by_id[view.view_id] = self._generate(view, style_anchor=anchor)
        views = tuple(
            GeneratedView(view_id=view.view_id, image=generated_by_id[view.view_id])
            for view in request.views
        )
        return GeneratedViewSet(request_id=request.request_id, views=views)
