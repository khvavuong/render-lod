"""Ask a vision model whether a generated view still shows the authored building count.

The deterministic edge screen cannot see an invented building: an extra volume sits far from
every authoritative edge, and those edges are discarded before scoring. Two pixel heuristics
were measured against reviewed output and both failed to separate a correct view from one with
two invented sheds, so this gate asks a vision model to count instead. Its answer is advisory
evidence for review, never a geometry certification.
"""

from __future__ import annotations

import base64
import json
import mimetypes
import re
from dataclasses import dataclass
from pathlib import Path

import httpx

from v365_archviz.config import Settings
from v365_archviz.errors import ConfigurationError, ProviderError

DEFAULT_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/interactions"

_PROMPT = """You are auditing an architectural visualisation for factual errors.

IMAGE 1 is the authoritative geometry: a plain untextured render of the approved model.
IMAGE 2 is a photorealistic image generated from IMAGE 1. It must show the same buildings.

The whole project contains {volumes} roofed building volume(s), but this camera may not see all
of them. Judge IMAGE 2 against what IMAGE 1 actually shows, not against the project total.

Count the separate roofed building volumes visible inside the site boundary (the fenced project
area) in each image. Count one volume per continuous roof; a long shed under one continuous roof
is one volume even when it has many bays, doors or dock canopies. Do not count neighbouring
buildings outside the site fence, and do not count small canopies, guard houses, plant
enclosures or a volume that is only marginally clipped at the frame edge in both images.

Reply with JSON only, no prose:
{{"base_volume_count": <int>,
  "generated_volume_count": <int>,
  "matches": <true if the two counts are equal, else false>,
  "notes": "<one short sentence naming any building present in IMAGE 2 but absent in IMAGE 1>"}}"""


@dataclass(frozen=True, slots=True)
class MassingVerdict:
    view_id: str
    expected_volume_count: int
    base_volume_count: int | None
    generated_volume_count: int | None
    matches: bool | None
    notes: str
    raw_response: str

    @property
    def status(self) -> str:
        if self.matches is None:
            return "unverified"
        return "pass" if self.matches else "fail"


def _image_block(path: Path) -> dict[str, str]:
    if not path.is_file():
        raise ProviderError(f"audit image does not exist: {path}")
    media_type = mimetypes.guess_type(path.name)[0] or "image/png"
    return {
        "type": "image",
        "mime_type": media_type,
        "data": base64.b64encode(path.read_bytes()).decode("ascii"),
    }


def _extract_json(text: str) -> dict[str, object] | None:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match is None:
        return None
    try:
        value = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _collect_text(value: object) -> str:
    """Pull every text fragment out of a provider response of unknown shape."""

    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        if value.get("type") == "text" and isinstance(value.get("text"), str):
            return str(value["text"])
        return " ".join(_collect_text(item) for item in value.values())
    if isinstance(value, list):
        return " ".join(_collect_text(item) for item in value)
    return ""


class GeminiMassingJudge:
    """Count authored versus generated building volumes with a vision model."""

    def __init__(
        self,
        settings: Settings,
        *,
        client: httpx.Client | None = None,
        endpoint: str = DEFAULT_ENDPOINT,
        model: str | None = None,
    ) -> None:
        api_key = settings.gemini_api_key
        if not api_key:
            raise ConfigurationError("GEMINI_API_KEY is required for massing verification")
        self._settings = settings
        self._api_key = api_key
        self._client = client or httpx.Client(timeout=httpx.Timeout(120.0, connect=10.0))
        self._owns_client = client is None
        self._endpoint = endpoint
        self._model = model or settings.gemini_image_model

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> GeminiMassingJudge:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def verify(
        self,
        view_id: str,
        base_render: Path,
        generated_image: Path,
        expected_volume_count: int,
    ) -> MassingVerdict:
        payload = {
            "model": self._model,
            "input": [
                {"type": "text", "text": _PROMPT.format(volumes=expected_volume_count)},
                _image_block(base_render),
                _image_block(generated_image),
            ],
            "store": self._settings.gemini_store_interactions,
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
            raise ProviderError("Gemini massing verification request failed") from exc

        text = _collect_text(body)
        document = _extract_json(text)
        if document is None:
            return MassingVerdict(
                view_id=view_id,
                expected_volume_count=expected_volume_count,
                base_volume_count=None,
                generated_volume_count=None,
                matches=None,
                notes="provider did not return a parsable verdict",
                raw_response=text[:2000],
            )
        raw_count = document.get("generated_volume_count")
        raw_base = document.get("base_volume_count")
        count = int(raw_count) if isinstance(raw_count, int | float) else None
        base_count = int(raw_base) if isinstance(raw_base, int | float) else None
        # Compare against what the base render shows from this camera, not the project total: a
        # ground-level arrival shot legitimately sees fewer volumes than the site contains, and
        # judging it against the total reports a drift that never happened.
        matches = None if count is None or base_count is None else count == base_count
        notes = document.get("notes")
        return MassingVerdict(
            view_id=view_id,
            expected_volume_count=expected_volume_count,
            base_volume_count=base_count,
            generated_volume_count=count,
            matches=matches,
            notes=str(notes) if isinstance(notes, str) else "",
            raw_response=text[:2000],
        )
