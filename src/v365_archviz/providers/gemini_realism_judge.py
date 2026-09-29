"""Ask a vision model whether a generated view is as photographic as the approved master.

Studio sets are anchored to one concept image, and the views generated after it did not always
hold its quality: a close view kept the flat surfaces of the conditioning render and read as CGI
beside a detailed master. Nothing compared them, so the weakest image reached the client. This
judge sees the master and one view side by side and answers only that question; composition,
design and taste are not its business.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import httpx

from v365_archviz.config import Settings
from v365_archviz.errors import ConfigurationError, ProviderError
from v365_archviz.providers.gemini_artefact_judge import (
    DEFAULT_ENDPOINT,
    _boolean,
    _collect_text,
    _extract_json,
    _image_block,
)

_PROMPT = """You are checking one photograph of a photo set against the set's approved image.

Both show the same industrial project from different cameras. Ignore the difference in camera,
framing and what is in view. Judge only the photographic finish of the CANDIDATE compared with
the REFERENCE.

cgi_look — does the candidate look like a 3D render rather than a photograph? Count: flat or
plastic surfaces, untextured cladding without panel ribs or joints, perfectly clean uniform
ground, toy-like vehicles or trees, missing weathering, soft or smeared detail, video-game
lighting.

less_detailed — does the candidate carry clearly less material and construction detail, or
clearly lower sharpness, than the reference at comparable viewing distance?

Reply with JSON only, no prose:
{"cgi_look": <true|false>,
 "less_detailed": <true|false>,
 "notes": "<one short sentence naming what looks rendered or soft, or empty if it matches>"}"""


@dataclass(frozen=True, slots=True)
class RealismVerdict:
    view_id: str
    cgi_look: bool | None
    less_detailed: bool | None
    notes: str
    raw_response: str

    @property
    def status(self) -> str:
        """`unverified` when the model did not answer, so silence never forces a paid retry."""

        if self.cgi_look is None or self.less_detailed is None:
            return "unverified"
        return "fail" if self.cgi_look or self.less_detailed else "pass"


class GeminiRealismJudge:
    """Compare one generated view with the set's master for photographic parity."""

    def __init__(
        self,
        settings: Settings,
        client: httpx.Client | None = None,
        endpoint: str = DEFAULT_ENDPOINT,
        model: str | None = None,
    ) -> None:
        if not settings.gemini_api_key:
            raise ConfigurationError("GEMINI_API_KEY is required for realism proofing")
        self._api_key = settings.gemini_api_key
        self._client = client
        self._endpoint = endpoint
        self._model = model or settings.gemini_image_model

    def compare(self, view_id: str, candidate: Path, reference: Path) -> RealismVerdict:
        body = {
            "model": self._model,
            "input": [
                {"type": "text", "text": _PROMPT},
                {"type": "text", "text": "REFERENCE (approved):"},
                _image_block(reference),
                {"type": "text", "text": "CANDIDATE:"},
                _image_block(candidate),
            ],
        }
        headers = {"x-goog-api-key": self._api_key}
        client = self._client or httpx.Client(timeout=120.0)
        try:
            response = client.post(self._endpoint, json=body, headers=headers)
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPError as exc:
            raise ProviderError("Gemini realism proofing request failed") from exc
        finally:
            if self._client is None:
                client.close()

        text = _collect_text(payload)
        document = _extract_json(text)
        if document is None:
            return RealismVerdict(view_id, None, None, "", text)
        return RealismVerdict(
            view_id=view_id,
            cgi_look=_boolean(document, "cgi_look"),
            less_detailed=_boolean(document, "less_detailed"),
            notes=str(document.get("notes", "")),
            raw_response=text,
        )
