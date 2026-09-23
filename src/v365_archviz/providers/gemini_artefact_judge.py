"""Ask a vision model whether a finished image carries visible generation artefacts.

This is separated from the aesthetic ranking on measured grounds. The selection judge lists
warped lettering among five things to weigh, and in blind validation it still chose an image whose
signage read "LO... LOGISTICA SOLUTIONS" — duplicated and smeared — over a clean alternative. A
defect that a viewer notices first should not be competing for attention with the quality of the
light; it gets its own question, and a candidate that fails it is removed rather than out-scored.

Garbled text is the artefact people see before anything else in an AI image, so it is asked about
first and by name. The rest are the failures this pipeline has actually produced: translucent
placeholder volumes surviving the context composite, and smeared or impossible structure.
"""

from __future__ import annotations

import base64
import json
import mimetypes
import re
from dataclasses import dataclass
from pathlib import Path

import httpx
from PIL import Image

from v365_archviz.config import Settings
from v365_archviz.errors import ConfigurationError, ProviderError

DEFAULT_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/interactions"

_PROMPT = """You are proofing a photograph before it goes into a printed brochure.

Look only for defects that would embarrass the publisher. Ignore whether you like the design, the
light or the composition — those are judged elsewhere.

Answer these, looking closely:

lettering — is any visible text malformed? Count as malformed: letters that are duplicated,
overlapping, smeared, reversed, cut off mid-word, or arranged into something that is not a real
word. Signage, wayfinding and vehicle liveries all count. Clean text in any language is fine, and
so is text too small or too distant to read.

placeholder — is any volume in the image flat, translucent, untextured or ghost-like, as if a
massing block had been left in a finished photograph?

structure — is any part of the building physically impossible, melted, or smeared into an
unreadable mess: a roof that does not meet its walls, a column passing through a window, repeated
geometry that could not be built?

Reply with JSON only, no prose:
{"lettering_defect": <true|false>,
 "placeholder_volume": <true|false>,
 "impossible_structure": <true|false>,
 "worst": "<lettering|placeholder|structure|none>",
 "notes": "<one short sentence naming what you saw, or empty if the image is clean>"}"""


@dataclass(frozen=True, slots=True)
class ArtefactVerdict:
    view_id: str
    lettering_defect: bool | None
    placeholder_volume: bool | None
    impossible_structure: bool | None
    worst: str
    notes: str
    raw_response: str

    @property
    def status(self) -> str:
        """`unverified` when the model did not answer, so silence is never a clean bill."""

        answers = (self.lettering_defect, self.placeholder_volume, self.impossible_structure)
        if any(answer is None for answer in answers):
            return "unverified"
        if self.lettering_defect or self.impossible_structure:
            return "fail"
        if self.placeholder_volume:
            # A surviving placeholder is ugly but it is also the one defect a different context
            # policy fixes wholesale, so it is worth flagging rather than discarding the image.
            return "review"
        return "pass"


def _image_block(path: Path) -> dict[str, str]:
    if not path.is_file():
        raise ProviderError(f"image does not exist: {path}")
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


def _boolean(document: dict[str, object], key: str) -> bool | None:
    value = document.get(key)
    return bool(value) if isinstance(value, bool) else None


class GeminiArtefactJudge:
    """Proof one finished image for defects a reader would notice before anything else."""

    def __init__(
        self,
        settings: Settings,
        client: httpx.Client | None = None,
        endpoint: str = DEFAULT_ENDPOINT,
        model: str | None = None,
    ) -> None:
        if not settings.gemini_api_key:
            raise ConfigurationError("GEMINI_API_KEY is required for artefact proofing")
        self._settings = settings
        self._client = client
        self._endpoint = endpoint
        self._model = model or settings.gemini_image_model

    def proof(self, view_id: str, image: Path, *, tiles: int = 1) -> ArtefactVerdict:
        """Proof the image, optionally in tiles.

        A whole 2752x1536 frame sent in one piece hides small defects: an orphaned "LO" beside a
        sign occupies about one percent of the width, and asked directly about lettering the model
        still reported the frame clean. Splitting into tiles makes the same text large relative to
        what is being looked at. Any tile reporting a defect condemns the image, because a defect
        in a corner is still in the brochure.
        """

        if tiles <= 1:
            return self._proof_one(view_id, image)
        with Image.open(image) as handle:
            frame = handle.convert("RGB")
            width, height = frame.size
            columns = tiles
            rows = max(1, tiles // 2)
            crops = []
            for row in range(rows):
                for column in range(columns):
                    box = (
                        int(width * column / columns),
                        int(height * row / rows),
                        int(width * (column + 1) / columns),
                        int(height * (row + 1) / rows),
                    )
                    crops.append(frame.crop(box))
        worst: ArtefactVerdict | None = None
        for index, crop in enumerate(crops):
            scratch = image.parent / f".artefact_tile_{index}.jpg"
            crop.save(scratch, quality=94)
            try:
                verdict = self._proof_one(view_id, scratch)
            finally:
                scratch.unlink(missing_ok=True)
            if verdict.status == "fail":
                return verdict
            if worst is None or verdict.status == "review":
                worst = verdict
        return worst or self._proof_one(view_id, image)

    def _proof_one(self, view_id: str, image: Path) -> ArtefactVerdict:
        body = {
            "model": self._model,
            "input": [
                {"type": "text", "text": _PROMPT},
                {"type": "text", "text": "IMAGE:"},
                _image_block(image),
            ],
        }
        headers = {"x-goog-api-key": self._settings.gemini_api_key}
        client = self._client or httpx.Client(timeout=120.0)
        try:
            response = client.post(self._endpoint, json=body, headers=headers)
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPError as exc:
            raise ProviderError("Gemini artefact proofing request failed") from exc
        finally:
            if self._client is None:
                client.close()

        text = _collect_text(payload)
        document = _extract_json(text)
        if document is None:
            return ArtefactVerdict(view_id, None, None, None, "", "", text)
        worst = document.get("worst")
        return ArtefactVerdict(
            view_id=view_id,
            lettering_defect=_boolean(document, "lettering_defect"),
            placeholder_volume=_boolean(document, "placeholder_volume"),
            impossible_structure=_boolean(document, "impossible_structure"),
            worst=str(worst) if isinstance(worst, str) else "",
            notes=str(document.get("notes", "")),
            raw_response=text,
        )
