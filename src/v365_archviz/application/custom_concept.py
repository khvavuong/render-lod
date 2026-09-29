"""A concept from the user's own description, alongside the five presets.

The description goes to the image model as the client's direction for the whole look. It is
screened first, so it cannot reopen locked geometry or override the system's rules; what is left
sits on the most neutral preset, whose finishes are only placeholders for the conditioning render.
"""

from __future__ import annotations

import hashlib

from v365_archviz.application.compile_user_intent import screen_free_text
from v365_archviz.application.studio import ConceptPreset, find_concept_presets
from v365_archviz.errors import InvalidModelError

BASE_PRESET_ID = "refined_minimal"
CUSTOM_CONCEPT_NAME = "Your concept"
SUMMARY_LIMIT = 240


def prompt_preset(prompt: str) -> ConceptPreset:
    """A preset whose look is the user's screened description."""

    screened, _ignored = screen_free_text(prompt, "prompt")
    if not screened:
        raise InvalidModelError("the description asks for nothing that can be designed")
    (base,) = find_concept_presets((BASE_PRESET_ID,))
    brief = dict(base.brief)
    brief["design_preferences"] = {
        **brief.get("design_preferences", {}),
        "client_prompt": screened,
    }
    summary = (
        screened if len(screened) <= SUMMARY_LIMIT else screened[: SUMMARY_LIMIT - 1].rstrip() + "…"
    )
    return ConceptPreset(
        preset_id=f"custom-{hashlib.sha256(screened.encode()).hexdigest()[:10]}",
        order=base.order,
        name=CUSTOM_CONCEPT_NAME,
        summary=summary,
        brief=brief,
    )
