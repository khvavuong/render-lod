"""Locate the project's buildings in a base render and in the photograph made from it.

Told to give the office more design, the image model sometimes lowered or turned the camera to
show it off, and the edge gate did not notice: a recomposed photograph still shares enough
straight lines with the render. Asked outright whether the camera moved, a vision model said yes
to nearly every photograph. Asked where each building stands in both images, it answers
consistently, and the overlap of those boxes separates kept from moved cameras cleanly.
"""

from __future__ import annotations

from pathlib import Path

import httpx

from v365_archviz.config import Settings
from v365_archviz.errors import ConfigurationError, ProviderError
from v365_archviz.providers.gemini_artefact_judge import (
    DEFAULT_ENDPOINT,
    _collect_text,
    _extract_json,
    _image_block,
)

#: [ymin, xmin, ymax, xmax], each 0 to 1000 of the image.
Box = tuple[float, float, float, float]

_PROMPT = """Both images show the same industrial project, which has {count} buildings on its
site. Image A is an untextured render; image B is a photograph of it. For EACH image give the
bounding box of each of the project's {count} buildings (never a neighbour outside the site),
ordered from the leftmost to the rightmost by box centre, as [ymin, xmin, ymax, xmax]
normalised to 0-1000.

Reply with JSON only:
{{"a": [[ymin, xmin, ymax, xmax], ...], "b": [[ymin, xmin, ymax, xmax], ...]}}"""


class GeminiFramingJudge:
    """Boxes of the same buildings in a render and in the photograph made from it."""

    def __init__(
        self,
        settings: Settings,
        client: httpx.Client | None = None,
        endpoint: str = DEFAULT_ENDPOINT,
        model: str | None = None,
    ) -> None:
        if not settings.gemini_api_key:
            raise ConfigurationError("GEMINI_API_KEY is required for framing proofing")
        self._api_key = settings.gemini_api_key
        self._client = client
        self._endpoint = endpoint
        self._model = model or settings.gemini_image_model

    def locate(
        self, render: Path, photograph: Path, count: int
    ) -> tuple[tuple[Box, ...], tuple[Box, ...]] | None:
        """Matching boxes in both images, or None when the model gave no usable answer."""

        body = {
            "model": self._model,
            "input": [
                {"type": "text", "text": _PROMPT.format(count=count)},
                {"type": "text", "text": "Image A:"},
                _image_block(render),
                {"type": "text", "text": "Image B:"},
                _image_block(photograph),
            ],
        }
        headers = {"x-goog-api-key": self._api_key}
        client = self._client or httpx.Client(timeout=120.0)
        try:
            response = client.post(self._endpoint, json=body, headers=headers)
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPError as exc:
            raise ProviderError("Gemini framing proofing request failed") from exc
        finally:
            if self._client is None:
                client.close()

        document = _extract_json(_collect_text(payload))
        if document is None:
            return None
        render_boxes, photo_boxes = _boxes(document.get("a")), _boxes(document.get("b"))
        if not render_boxes or len(render_boxes) != len(photo_boxes):
            return None
        return render_boxes, photo_boxes


def _boxes(value: object) -> tuple[Box, ...]:
    if not isinstance(value, list):
        return ()
    boxes: list[Box] = []
    for item in value:
        if not (
            isinstance(item, list)
            and len(item) == 4
            and all(isinstance(number, int | float) for number in item)
        ):
            return ()
        boxes.append((float(item[0]), float(item[1]), float(item[2]), float(item[3])))
    return tuple(boxes)
