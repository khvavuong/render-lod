"""Veo 3.1 image-to-video adapter using the documented Gemini REST API."""

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
    VideoGenerationInput,
    VideoOperation,
)

DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"


def _inline_image(path: Path) -> dict[str, str]:
    if not path.is_file():
        raise ProviderError(f"video source image does not exist: {path}")
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    try:
        with Image.open(path) as image:
            if image.format:
                media_type = Image.MIME.get(image.format, media_type)
    except (UnidentifiedImageError, OSError) as exc:
        raise ProviderError(f"video source is not a readable image: {path}") from exc
    if not media_type.startswith("image/"):
        raise ProviderError(f"video source is not an image: {path}")
    return {
        "mimeType": media_type,
        "bytesBase64Encoded": base64.b64encode(path.read_bytes()).decode("ascii"),
    }


def _operation_from_body(body: Any) -> VideoOperation:
    if not isinstance(body, dict) or not isinstance(body.get("name"), str):
        raise ProviderError("Veo returned an invalid operation")
    error = body.get("error")
    error_message = None
    if isinstance(error, dict):
        message = error.get("message")
        error_message = message if isinstance(message, str) else "Veo operation failed"
    response = body.get("response")
    download_uri = None
    if isinstance(response, dict):
        generate_response = response.get("generateVideoResponse")
        if isinstance(generate_response, dict):
            samples = generate_response.get("generatedSamples")
            if isinstance(samples, list) and samples and isinstance(samples[0], dict):
                video = samples[0].get("video")
                if isinstance(video, dict) and isinstance(video.get("uri"), str):
                    download_uri = video["uri"]
    return VideoOperation(
        name=body["name"],
        done=body.get("done") is True,
        download_uri=download_uri,
        error_message=error_message,
    )


class VeoVideoRenderer:
    name = "veo"

    def __init__(
        self,
        settings: Settings,
        *,
        client: httpx.Client | None = None,
        base_url: str = DEFAULT_BASE_URL,
    ) -> None:
        if not settings.gemini_api_key:
            raise ConfigurationError("GEMINI_API_KEY is required for Veo generation")
        self._api_key = settings.gemini_api_key
        self._model = settings.veo_model
        self._client = client or httpx.Client(
            timeout=httpx.Timeout(120.0, connect=10.0), follow_redirects=True
        )
        self._owns_client = client is None
        self._base_url = base_url.rstrip("/")

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> VeoVideoRenderer:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _headers(self) -> dict[str, str]:
        return {"x-goog-api-key": self._api_key}

    def start(self, request: VideoGenerationInput) -> VideoOperation:
        payload = {
            "instances": [
                {
                    "prompt": (
                        f"{request.prompt}\nAvoid these failures: {request.negative_prompt}."
                    ),
                    "image": _inline_image(request.source_image),
                }
            ],
            "parameters": {
                "aspectRatio": request.aspect_ratio,
                "durationSeconds": request.duration_seconds,
                "personGeneration": "allow_adult",
                "resolution": request.resolution,
                "seed": request.seed,
            },
        }
        try:
            response = self._client.post(
                f"{self._base_url}/models/{self._model}:predictLongRunning",
                headers=self._headers(),
                json=payload,
            )
            response.raise_for_status()
            return _operation_from_body(response.json())
        except (httpx.HTTPError, ValueError) as exc:
            status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
            suffix = f" (HTTP {status})" if status else ""
            detail = ""
            if isinstance(exc, httpx.HTTPStatusError):
                try:
                    error = exc.response.json().get("error", {})
                    message = error.get("message") if isinstance(error, dict) else None
                    if isinstance(message, str):
                        detail = f": {message[:300]}"
                except ValueError:
                    pass
            raise ProviderError(f"Veo submission failed{suffix}{detail}") from exc

    def get(self, operation_name: str) -> VideoOperation:
        if (
            "/operations/" not in operation_name
            and not operation_name.startswith("operations/")
        ) or operation_name.startswith(("/", "http://", "https://")):
            raise ProviderError("invalid Veo operation name")
        try:
            response = self._client.get(
                f"{self._base_url}/{operation_name}", headers=self._headers()
            )
            response.raise_for_status()
            return _operation_from_body(response.json())
        except (httpx.HTTPError, ValueError) as exc:
            raise ProviderError("Veo operation polling failed") from exc

    def download(self, operation: VideoOperation) -> bytes:
        if not operation.done or operation.error_message or not operation.download_uri:
            raise ProviderError("Veo operation has no downloadable video")
        try:
            response = self._client.get(operation.download_uri, headers=self._headers())
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ProviderError("Veo video download failed") from exc
        media_type = response.headers.get("content-type", "")
        if media_type and not media_type.startswith("video/"):
            raise ProviderError("Veo download did not return video content")
        if not response.content:
            raise ProviderError("Veo returned an empty video")
        return response.content
