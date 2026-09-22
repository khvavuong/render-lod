"""OpenAI Image API adapter for design-master multi-view refinement."""

from __future__ import annotations

import base64
import io
import json
import mimetypes
from collections.abc import Callable
from pathlib import Path
from typing import TypeAlias

import httpx
from PIL import Image, UnidentifiedImageError

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

DEFAULT_ENDPOINT = "https://api.openai.com/v1/images/edits"

#: How many progressive previews the provider sends before the finished image.
_PARTIAL_IMAGES = 2

_FilePart: TypeAlias = tuple[str, tuple[str, bytes, str]]


def _edit_failed(exc: Exception) -> ProviderError:
    status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
    suffix = f" (HTTP {status})" if status else ""
    return ProviderError(f"OpenAI image edit request failed{suffix}")


def _sse_payload(line: str) -> dict[str, object] | None:
    """The JSON object in one `data:` line, or None for keep-alives and `[DONE]`."""

    if not line.startswith("data:"):
        return None
    body = line[len("data:") :].strip()
    if not body or body == "[DONE]":
        return None
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


class OpenAIImageRenderer:
    """Edit each geometry render while sharing one generated appearance authority."""

    name = "openai-image"
    capabilities = ImageProviderCapabilities(
        supports_masked_edit=True,
        supports_multi_reference=True,
    )

    def __init__(
        self,
        settings: Settings,
        *,
        client: httpx.Client | None = None,
        endpoint: str = DEFAULT_ENDPOINT,
    ) -> None:
        if not settings.openai_api_key:
            raise ConfigurationError(
                "OPENAI_API_KEY is required when V365_IMAGE_PROVIDER=openai-image"
            )
        if settings.openai_image_quality not in {
            "auto",
            "low",
            "medium",
            "high",
            "xhigh",
            "max",
        }:
            raise ConfigurationError("OPENAI_IMAGE_QUALITY is not supported")
        if settings.openai_image_size not in {
            "auto",
            "1024x1024",
            "1536x1024",
            "1024x1536",
        }:
            raise ConfigurationError("OPENAI_IMAGE_SIZE is not supported")
        self._api_key = settings.openai_api_key
        self._model = settings.openai_image_model
        self._quality = settings.openai_image_quality
        self._size = settings.openai_image_size
        self._client = client or httpx.Client(timeout=httpx.Timeout(300.0, connect=15.0))
        self._owns_client = client is None
        self._endpoint = endpoint

    @property
    def provenance(self) -> dict[str, object]:
        return {
            "endpoint_family": "images/edits",
            "model": self._model,
            "quality": self._quality,
            "requested_size": self._size,
            "viewset_strategy": "design-master-sequential",
            "geometry_protection": "validation-only",
        }

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> OpenAIImageRenderer:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    @staticmethod
    def _file(path: Path) -> tuple[str, tuple[str, bytes, str]]:
        if not path.is_file():
            raise ProviderError(f"conditioning image does not exist: {path}")
        media_type = mimetypes.guess_type(path.name)[0] or "image/png"
        return "image[]", (path.name, path.read_bytes(), media_type)

    @staticmethod
    def _memory_file(name: str, generated: GeneratedImage) -> tuple[str, tuple[str, bytes, str]]:
        return "image[]", (name, generated.content, generated.media_type)

    def _generate(
        self,
        request: ViewConditioningInput,
        *,
        identity_prompt: str = "",
        design_master: GeneratedImage | None = None,
    ) -> GeneratedImage:
        ordering = [
            "IMAGE 1 is the current base render and is the sole authority for camera, crop, "
            "massing, building count, roof continuity, roads, gates, fences, landscape regions "
            "and object positions."
        ]
        files = [self._file(request.base_rgb)]
        if design_master is not None:
            ordering.append(
                "IMAGE 2 is the approved Design Master for this exact project. Transfer only "
                "its facade language, materials, palette, daylight and photographic finish. "
                "Never copy its camera or spatial layout."
            )
            files.append(self._memory_file("design-master.png", design_master))
        for index, reference in enumerate(request.reference_images, start=len(files) + 1):
            ordering.append(
                f"IMAGE {index} is a realism-only reference. Borrow photographic credibility "
                "only; do not copy geometry, architecture, palette, site or camera."
            )
            files.append(self._file(reference))
        prompt = "\n\n".join(
            (
                request.prompt,
                identity_prompt,
                "INPUT AUTHORITY AND ORDER:\n" + "\n".join(ordering),
                "Return one photorealistic image only. Preserve a centered 16:9 safe frame; "
                "keep all important authored site edges away from the top and bottom crop area.",
            )
        )
        try:
            response = self._client.post(
                self._endpoint,
                headers={"authorization": f"Bearer {self._api_key}"},
                files=files,
                data={
                    "model": self._model,
                    "prompt": prompt,
                    "quality": self._quality,
                    "size": self._size,
                    "output_format": "png",
                },
            )
            response.raise_for_status()
            body = response.json()
            encoded = body["data"][0]["b64_json"]
            content = base64.b64decode(encoded, validate=True)
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as exc:
            status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
            suffix = f" (HTTP {status})" if status else ""
            raise ProviderError(f"OpenAI image edit request failed{suffix}") from exc
        content = self._normalize_aspect(content, request.aspect_ratio)
        return GeneratedImage(
            content=content,
            media_type="image/png",
            provider_request_id=response.headers.get("x-request-id"),
        )

    @staticmethod
    def _normalize_aspect(content: bytes, aspect_ratio: str) -> bytes:
        """Center-crop provider sizes to the camera contract without stretching geometry."""

        try:
            width_text, height_text = aspect_ratio.split(":", maxsplit=1)
            target_ratio = int(width_text) / int(height_text)
            with Image.open(io.BytesIO(content)) as source:
                image = source.convert("RGB")
        except (OSError, UnidentifiedImageError, ValueError, ZeroDivisionError) as exc:
            raise ProviderError("OpenAI returned an invalid image") from exc
        current_ratio = image.width / image.height
        if abs(current_ratio - target_ratio) > 0.001:
            if current_ratio > target_ratio:
                width = round(image.height * target_ratio)
                left = (image.width - width) // 2
                image = image.crop((left, 0, left + width, image.height))
            else:
                height = round(image.width / target_ratio)
                top = (image.height - height) // 2
                image = image.crop((0, top, image.width, top + height))
        buffer = io.BytesIO()
        image.save(buffer, format="PNG", optimize=True)
        return buffer.getvalue()

    def _edit_request(self, request: ViewEditInput) -> tuple[list[_FilePart], dict[str, str]]:
        """The multipart body an edit sends, shared by the buffered and streamed paths."""

        files: list[_FilePart] = [self._file(request.base_image)]
        ordering = [
            "IMAGE 1 is the current approved render of this view and is the sole authority "
            "for camera, crop, massing, building count, roof continuity, roads, gates, "
            "fences, landscape regions and object positions."
        ]
        if request.mask is not None:
            files.append(("mask", ("mask.png", request.mask, "image/png")))
            ordering.append(
                "The mask marks the only region you may repaint. Every pixel outside it must "
                "return byte-for-byte unchanged."
            )
        for index, reference in enumerate(request.reference_images, start=2):
            ordering.append(
                f"IMAGE {index} is a realism-only reference. Borrow photographic credibility "
                "only; do not copy geometry, architecture, palette, site or camera."
            )
            files.append(self._file(reference))
        prompt = "\n\n".join(
            (
                request.prompt,
                "INPUT AUTHORITY AND ORDER:\n" + "\n".join(ordering),
                "Return one photorealistic image only, matching the existing lighting, "
                "palette and photographic finish of IMAGE 1 at the mask boundary.",
            )
        )
        data = {
            "model": self._model,
            "prompt": prompt,
            "quality": request.quality or self._quality,
            "size": request.size or self._size,
            "output_format": "png",
            "n": str(request.candidates),
        }
        return files, data

    def edit(
        self,
        request: ViewEditInput,
        *,
        on_partial: Callable[[int, bytes], None] | None = None,
    ) -> tuple[GeneratedImage, ...]:
        """Redraw only what the mask exposes, leaving the rest of the view alone.

        The base render is IMAGE 1 exactly as in `_generate`, so the wording that
        makes it the authority for camera and massing still holds. The mask is
        what narrows the change to the region a person drew.

        `on_partial` receives the provider's progressive previews. Asking for
        several candidates turns streaming off, because the endpoint interleaves
        their previews and a half-drawn image is not worth that bookkeeping.
        """

        if request.candidates < 1 or request.candidates > 4:
            raise ProviderError("an edit must ask for between one and four candidates")
        files, data = self._edit_request(request)
        if on_partial is not None and request.candidates == 1:
            contents, request_id = self._edit_streamed(files, data, on_partial)
        else:
            contents, request_id = self._edit_buffered(files, data)
        return tuple(
            GeneratedImage(
                content=self._normalize_aspect(content, request.aspect_ratio),
                media_type="image/png",
                provider_request_id=request_id,
            )
            for content in contents
        )

    def _edit_buffered(
        self,
        files: list[_FilePart],
        data: dict[str, str],
    ) -> tuple[tuple[bytes, ...], str | None]:
        try:
            response = self._client.post(
                self._endpoint,
                headers={"authorization": f"Bearer {self._api_key}"},
                files=files,
                data=data,
            )
            response.raise_for_status()
            body = response.json()
            encoded = tuple(str(item["b64_json"]) for item in body["data"])
            if not encoded:
                raise ProviderError("OpenAI returned no image for the edit")
            contents = tuple(base64.b64decode(value, validate=True) for value in encoded)
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as exc:
            raise _edit_failed(exc) from exc
        return contents, response.headers.get("x-request-id")

    def _edit_streamed(
        self,
        files: list[_FilePart],
        data: dict[str, str],
        on_partial: Callable[[int, bytes], None],
    ) -> tuple[tuple[bytes, ...], str | None]:
        """Read the provider's server-sent events, forwarding each preview as it lands."""

        streamed = dict(data, stream="true", partial_images=str(_PARTIAL_IMAGES))
        contents: list[bytes] = []
        request_id: str | None = None
        try:
            with self._client.stream(
                "POST",
                self._endpoint,
                headers={"authorization": f"Bearer {self._api_key}"},
                files=files,
                data=streamed,
            ) as response:
                response.raise_for_status()
                request_id = response.headers.get("x-request-id")
                for line in response.iter_lines():
                    event = _sse_payload(line)
                    if event is None:
                        continue
                    encoded = event.get("b64_json")
                    if not isinstance(encoded, str):
                        continue
                    decoded = base64.b64decode(encoded, validate=True)
                    if event.get("type") == "image_edit.partial_image":
                        index = event.get("partial_image_index")
                        on_partial(int(index) if isinstance(index, int) else 0, decoded)
                    elif event.get("type") == "image_edit.completed":
                        contents.append(decoded)
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as exc:
            raise _edit_failed(exc) from exc
        if not contents:
            raise ProviderError("OpenAI streamed no completed image for the edit")
        return tuple(contents), request_id

    def generate(self, request: ViewConditioningInput) -> GeneratedImage:
        return self._generate(request)

    def generate_view_set(self, request: ViewSetGenerationInput) -> GeneratedViewSet:
        if not request.views:
            return GeneratedViewSet(request_id=request.request_id, views=())
        master_request = next(
            (view for view in request.views if view.view_id == request.master_view_id),
            request.views[0],
        )
        master = self._generate(master_request, identity_prompt=request.identity_prompt)
        by_id = {master_request.view_id: master}
        for view in request.views:
            if view.view_id != master_request.view_id:
                by_id[view.view_id] = self._generate(
                    view,
                    identity_prompt=request.identity_prompt,
                    design_master=master,
                )
        return GeneratedViewSet(
            request_id=request.request_id,
            views=tuple(
                GeneratedView(view_id=view.view_id, image=by_id[view.view_id])
                for view in request.views
            ),
        )
