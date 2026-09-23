"""Ask a vision model whether a generated view still stands on the camera it was conditioned on.

The deterministic edge screen was measured against 18 reviewed views and rejected 11 of them, of
which exactly one had a real geometry problem. It rejected four of the six views of the set a
reviewer rated best, including one where the camera provably had not moved. It cannot separate
"the provider redrew the cladding" from "the provider rebuilt the camera", because both change
edges under the locked mask.

The massing judge answers a different question the same way and has worked: on this project it
caught every invented building a reviewer later confirmed. This judge extends that pattern to the
questions the edge screen was failing to answer — viewpoint, placement and openings — by asking
them in plain language against the two images and taking a structured answer back.

Like the massing judge, its verdict is evidence for review, not a geometry certification.
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

IMAGE 1 is the authoritative render: a plain untextured view of the approved model.
IMAGE 2 is a photorealistic image generated from IMAGE 1.

IMAGE 2 is allowed to look completely different in materials, colour, facade detail, glazing,
canopies, signage, planting, vehicles, people, sky and light. Judge none of that.

Judge only whether IMAGE 2 was taken from the same camera as IMAGE 1, and whether the buildings
sit where IMAGE 1 puts them.

viewpoint — compare where the camera stands, not what the building is made of:
  "same"      the same position, height and direction; the same faces of the building are visible
              in the same places, and the horizon sits at the same height
  "shifted"   recognisably the same shot, but panned, cropped or zoomed
  "different" a different position, height or direction: other faces visible, a different
              silhouette against the sky, or an aerial where IMAGE 1 is at eye level

placement — do the main building volumes occupy the same positions and proportions in the frame,
allowing for new canopies, parapets and facade depth?

openings — does every large vehicular opening or loading dock visible in IMAGE 1 still appear in
IMAGE 2, on the same facade and in the same order? Ignore windows and doors for people.

Reply with JSON only, no prose:
{"viewpoint": "<same|shifted|different>",
 "placement_matches": <true|false>,
 "openings_match": <true|false>,
 "notes": "<one short sentence naming the clearest discrepancy, or empty if none>"}"""


@dataclass(frozen=True, slots=True)
class ViewVerdict:
    view_id: str
    viewpoint: str | None
    placement_matches: bool | None
    openings_match: bool | None
    notes: str
    raw_response: str

    @property
    def status(self) -> str:
        """`unverified` when the model did not answer, so silence never reads as approval."""

        if (
            self.viewpoint not in {"same", "shifted", "different"}
            or self.placement_matches is None
            or self.openings_match is None
        ):
            return "unverified"
        # A pan or a crop keeps the same shot and is recoverable; a rebuilt camera is not, and a
        # building that moved is the failure the edge screen was meant to catch and did not.
        if self.viewpoint == "different" or not self.placement_matches:
            return "fail"
        if self.viewpoint == "shifted" or self.openings_match is False:
            return "review"
        return "pass"


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
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        if value.get("type") == "text" and isinstance(value.get("text"), str):
            return str(value["text"])
        return " ".join(_collect_text(item) for item in value.values())
    if isinstance(value, list):
        return " ".join(_collect_text(item) for item in value)
    return ""


class GeminiViewJudge:
    """Audit one generated view against the render it was conditioned on."""

    def __init__(
        self,
        settings: Settings,
        client: httpx.Client | None = None,
        endpoint: str = DEFAULT_ENDPOINT,
        model: str | None = None,
    ) -> None:
        if not settings.gemini_api_key:
            raise ConfigurationError("GEMINI_API_KEY is required for view verification")
        self._settings = settings
        self._client = client
        self._endpoint = endpoint
        self._model = model or settings.gemini_image_model

    def verify(self, view_id: str, base_rgb: Path, generated: Path) -> ViewVerdict:
        body = {
            "model": self._model,
            "input": [
                {"type": "text", "text": _PROMPT},
                {"type": "text", "text": "IMAGE 1 — authoritative render:"},
                _image_block(base_rgb),
                {"type": "text", "text": "IMAGE 2 — generated image:"},
                _image_block(generated),
            ],
        }
        headers = {"x-goog-api-key": self._settings.gemini_api_key}
        client = self._client or httpx.Client(timeout=120.0)
        try:
            response = client.post(self._endpoint, json=body, headers=headers)
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPError as exc:
            raise ProviderError("Gemini view verification request failed") from exc
        finally:
            if self._client is None:
                client.close()

        text = _collect_text(payload)
        document = _extract_json(text)
        if document is None:
            return ViewVerdict(view_id, None, None, None, "", text)
        viewpoint = document.get("viewpoint")
        return ViewVerdict(
            view_id=view_id,
            viewpoint=str(viewpoint) if viewpoint in {"same", "shifted", "different"} else None,
            placement_matches=(
                bool(document["placement_matches"])
                if isinstance(document.get("placement_matches"), bool)
                else None
            ),
            openings_match=(
                bool(document["openings_match"])
                if isinstance(document.get("openings_match"), bool)
                else None
            ),
            notes=str(document.get("notes", "")),
            raw_response=text,
        )
