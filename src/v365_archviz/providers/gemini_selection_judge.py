"""Rank several candidate images of one view and say which is the better photograph.

Every view in this pipeline has been generated once and shipped, which is not how a marketing
image is made. Generating a few and choosing is the cheapest way to raise the ceiling, but it
needs a selector, and the ceiling it raises is aesthetic rather than factual — so this judge is
asked only about the photograph, never about whether the geometry is right. The massing and view
audits answer that separately, and a candidate they reject is removed before this judge sees it.

The ranking is advisory. It exists to order a shortlist a person can still overrule, not to
replace the blind review the research plan asks for.
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

_PROMPT = """You are an architectural photography editor choosing which frame to publish.

The images that follow are alternative photographs of the same industrial project from the same
camera. They show the same building, so do not judge which design you prefer, and do not judge
whether the model is accurate — that has already been checked.

Judge only which is the better published photograph, on:
  - does it read as a photograph rather than a render
  - light: direction, contrast, whether shadows give the building form
  - material credibility: seams, fixings, wear, ground contact
  - composition: what the frame gives to the building and to its setting
  - freedom from artefacts: flat grey or translucent placeholder volumes, warped signage or
    lettering, impossible geometry, smeared detail

Reply with JSON only, no prose:
{"ranking": [<1-based image numbers, best first>],
 "best": <the best image number>,
 "reason": "<one short sentence on what decided it>",
 "artefacts": {"<image number>": "<artefact seen, if any>"}}"""


@dataclass(frozen=True, slots=True)
class SelectionVerdict:
    view_id: str
    ranking: tuple[int, ...]
    best_index: int | None
    reason: str
    artefacts: dict[str, str]
    raw_response: str

    @property
    def decided(self) -> bool:
        return self.best_index is not None


def _image_block(path: Path) -> dict[str, str]:
    if not path.is_file():
        raise ProviderError(f"candidate image does not exist: {path}")
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


class GeminiSelectionJudge:
    """Choose the best of several candidate photographs of one view."""

    def __init__(
        self,
        settings: Settings,
        client: httpx.Client | None = None,
        endpoint: str = DEFAULT_ENDPOINT,
        model: str | None = None,
    ) -> None:
        if not settings.gemini_api_key:
            raise ConfigurationError("GEMINI_API_KEY is required for candidate selection")
        self._settings = settings
        self._client = client
        self._endpoint = endpoint
        self._model = model or settings.gemini_image_model

    def choose(self, view_id: str, candidates: tuple[Path, ...]) -> SelectionVerdict:
        if not candidates:
            raise ProviderError(f"{view_id} has no candidates to choose between")
        if len(candidates) == 1:
            return SelectionVerdict(
                view_id, (1,), 1, "only one candidate survived the gates", {}, ""
            )
        blocks: list[dict[str, str]] = [{"type": "text", "text": _PROMPT}]
        for index, path in enumerate(candidates, start=1):
            blocks.append({"type": "text", "text": f"IMAGE {index}:"})
            blocks.append(_image_block(path))
        body = {"model": self._model, "input": blocks}
        headers = {"x-goog-api-key": self._settings.gemini_api_key}
        client = self._client or httpx.Client(timeout=180.0)
        try:
            response = client.post(self._endpoint, json=body, headers=headers)
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPError as exc:
            raise ProviderError("Gemini candidate selection request failed") from exc
        finally:
            if self._client is None:
                client.close()

        text = _collect_text(payload)
        document = _extract_json(text)
        if document is None:
            return SelectionVerdict(view_id, (), None, "", {}, text)
        raw_ranking = document.get("ranking")
        ranking = tuple(
            int(value)
            for value in (raw_ranking if isinstance(raw_ranking, list) else [])
            if isinstance(value, int) and 1 <= value <= len(candidates)
        )
        best = document.get("best")
        best_index = (
            int(best)
            if isinstance(best, int) and 1 <= best <= len(candidates)
            else (ranking[0] if ranking else None)
        )
        artefacts = document.get("artefacts")
        return SelectionVerdict(
            view_id=view_id,
            ranking=ranking,
            best_index=best_index,
            reason=str(document.get("reason", "")),
            artefacts={str(k): str(v) for k, v in artefacts.items()}
            if isinstance(artefacts, dict)
            else {},
            raw_response=text,
        )
