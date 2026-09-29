"""Gemini image-generation adapter with privacy-safe defaults."""

from __future__ import annotations

import base64
import io
import json
import mimetypes
from collections.abc import Callable
from enum import Enum
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
    ImageProviderCapabilities,
    ViewConditioningInput,
    ViewEditInput,
    ViewSetGenerationInput,
)

DEFAULT_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/interactions"


class GeminiConditioningMode(str, Enum):
    """Versioned input strategies used by the controlled-realism bake-off."""

    FULL = "full"
    MINIMAL = "minimal"
    PHOTOREAL_BALANCED = "photoreal_balanced"


#: Roles whose camera looks down on the whole site. The aerial site-plan conditioning block is
#: keyed on these rather than on a view id, because camera selection assigns slots by what a site
#: can actually offer and "view-01" is not always the overview.
_AERIAL_ROLES = frozenset({"overall", "detail"})

_STRUCTURE_AUTHORITY_BY_FREEDOM = {
    "photoreal_only": (
        "MONOCHROME STRUCTURE AUTHORITY — preserve its project silhouette, roof continuity, "
        "facade bay boundaries and exact authored/proposed opening count. It is a constraint "
        "image, not a material or style target. Any outlined off-site proxy is reserved for "
        "deterministic post-composite; do not turn it into a detailed building:"
    ),
    "detail_within_envelope": (
        "MONOCHROME STRUCTURE AUTHORITY — preserve its project silhouette, roof continuity and "
        "the position and count of every vehicular opening. The facade bay lines are "
        "where emphasis belongs, not a finished design: you may develop how each bay is "
        "composed, framed and shaded within them. It is a constraint image, not a material or "
        "style target. Any outlined off-site proxy is reserved for deterministic post-composite; "
        "do not turn it into a detailed building:"
    ),
    "design_within_envelope": (
        "MONOCHROME STRUCTURE AUTHORITY — preserve its project silhouette, its footprint and the "
        "position of every vehicular opening, so trucks still reach the same doors. Everything "
        "drawn inside that outline is massing study, not design: bay lines, stripes and panel "
        "divisions are placeholders you are expected to replace. It is a constraint image, not a "
        "material or style target. Any outlined off-site proxy is reserved for deterministic "
        "post-composite; do not turn it into a detailed building:"
    ),
}


_BASE_RGB_LABEL_BY_FREEDOM = {
    "photoreal_only": ("BASE RGB — sole camera, geometry, composition and spatial authority:"),
    "detail_within_envelope": (
        "BASE RGB — sole camera and composition authority, and the authority for massing, "
        "roofline and the position of every opening. Its facade surfaces are a placed schematic "
        "you may develop, not finished design:"
    ),
    "design_within_envelope": (
        "BASE RGB — sole camera and composition authority, and the authority for the silhouette, "
        "the footprint and where the vehicular openings are. Everything drawn on its surfaces is "
        "an untextured massing study, not design: do not reproduce its colours, stripes, fins or "
        "panel divisions:"
    ),
}

_AUTHORITY_LINE_BY_FREEDOM = {
    "photoreal_only": "The current BASE RGB is the sole spatial and camera authority.",
    "detail_within_envelope": (
        "The current BASE RGB is the sole camera authority and fixes massing, roofline and "
        "opening positions; its facade surfaces are a schematic to develop."
    ),
    "design_within_envelope": (
        "The current BASE RGB is the sole camera authority and fixes the silhouette, footprint "
        "and opening positions; everything on its surfaces is massing study, not design."
    ),
}


def _base_rgb_label(design_freedom: str) -> str:
    """Describe what the base render is authoritative for at this freedom level.

    Declaring it the "sole geometry authority" on every request contradicts a prompt that has just
    granted facade freedom, and the image block is the more concrete of the two instructions. This
    was the same defect as the structure-authority block, in the same file, and it survived that
    fix: measured output kept reproducing the procedural fins after freedom was already default.
    """

    return _BASE_RGB_LABEL_BY_FREEDOM.get(
        design_freedom, _BASE_RGB_LABEL_BY_FREEDOM["photoreal_only"]
    )


def _authority_line(design_freedom: str) -> str:
    return _AUTHORITY_LINE_BY_FREEDOM.get(
        design_freedom, _AUTHORITY_LINE_BY_FREEDOM["photoreal_only"]
    )


def _structure_authority_text(design_freedom: str) -> str:
    """State the structure block at the freedom the style pack asked for.

    One text was sent on every request regardless. A pack granting design freedom therefore
    arrived with a prompt saying the facade was the provider's to design and a conditioning block
    demanding the authored bay boundaries and exact opening count back — two instructions in the
    same request that cannot both be followed.
    """

    return _STRUCTURE_AUTHORITY_BY_FREEDOM.get(
        design_freedom, _STRUCTURE_AUTHORITY_BY_FREEDOM["photoreal_only"]
    )


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


def _reference_role(path: Path) -> str:
    if path.name == "context_composition_guide.png":
        return "context_composition_guide"
    try:
        metadata = json.loads((path.parent / "metadata.json").read_text(encoding="utf-8"))
        role = metadata.get("role")
    except (OSError, json.JSONDecodeError):
        role = None
    return str(role) if role else "quality_only"


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
    capabilities = ImageProviderCapabilities(
        supports_multi_reference=True,
    )

    def __init__(
        self,
        settings: Settings,
        *,
        client: httpx.Client | None = None,
        endpoint: str = DEFAULT_ENDPOINT,
        conditioning_mode: GeminiConditioningMode = GeminiConditioningMode.FULL,
    ) -> None:
        api_key = settings.gemini_api_key
        if not api_key:
            raise ConfigurationError("GEMINI_API_KEY is required for Gemini generation")
        self._settings = settings
        self._api_key = api_key
        self._client = client or httpx.Client(timeout=httpx.Timeout(180.0, connect=10.0))
        self._owns_client = client is None
        self._endpoint = endpoint
        self._conditioning_mode = conditioning_mode

    @property
    def name(self) -> str:
        if self._conditioning_mode is GeminiConditioningMode.FULL:
            return "gemini"
        return f"gemini-{self._conditioning_mode.value}"

    @property
    def provenance(self) -> dict[str, object]:
        return {
            "model": self._settings.gemini_image_model,
            "master_model": (
                self._settings.gemini_master_image_model or self._settings.gemini_image_model
            ),
            "conditioning_mode": self._conditioning_mode.value,
            "input_policy": (
                "base_rgb+structure_authority+design_master+two_role_references"
                if self._conditioning_mode is GeminiConditioningMode.PHOTOREAL_BALANCED
                else "legacy_control_pass_conditioning"
            ),
            "store_interactions": self._settings.gemini_store_interactions,
            "thinking_level": self._settings.gemini_thinking_level,
        }

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
        identity_prompt: str = "",
        model: str | None = None,
    ) -> GeneratedImage:
        if request.generation_policy in {
            "reference-led-proposal-v1",
            "reference-led-registered-v1",
        }:
            from v365_archviz.application.reference_led_input import REFERENCE_INSTRUCTIONS

            if len(request.reference_images) != len(request.reference_roles):
                raise ProviderError("Proposal reference roles are missing")
            if request.reference_instructions and len(request.reference_instructions) != len(
                request.reference_roles
            ):
                raise ProviderError("Proposal reference instructions are missing")
            input_blocks = [{"type": "text", "text": request.prompt}]
            for index, (reference, role) in enumerate(
                zip(request.reference_images, request.reference_roles, strict=True)
            ):
                registered_roles = {"approved_design_anchor", "source_geometry_evidence"}
                if role not in REFERENCE_INSTRUCTIONS and not (
                    request.generation_policy == "reference-led-registered-v1"
                    and role in registered_roles
                    and request.reference_instructions
                ):
                    raise ProviderError("Unsupported proposal reference role")
                instruction = (
                    request.reference_instructions[index]
                    if request.reference_instructions
                    else REFERENCE_INSTRUCTIONS[role]
                )
                input_blocks.extend(
                    [
                        {"type": "text", "text": f"{role}: {instruction}"},
                        _image_block(reference),
                    ]
                )
        elif request.generation_policy != "legacy":
            raise ProviderError("Unknown generation policy")
        elif self._conditioning_mode is GeminiConditioningMode.PHOTOREAL_BALANCED:
            input_blocks = self._photoreal_balanced_input(
                request,
                style_anchor=style_anchor,
                identity_prompt=identity_prompt,
            )
        else:
            input_blocks = self._legacy_input(
                request,
                style_anchor=style_anchor,
                identity_prompt=identity_prompt,
            )
        selected_model = request.provider_model or model or self._settings.gemini_image_model
        payload = {
            "model": selected_model,
            "input": input_blocks,
            "store": False
            if request.generation_policy != "legacy"
            else self._settings.gemini_store_interactions,
            "response_format": {
                "type": "image",
                "aspect_ratio": request.aspect_ratio,
                "image_size": request.image_size,
            },
        }
        if "3.1-flash" in selected_model:
            payload["generation_config"] = {"thinking_level": self._settings.gemini_thinking_level}

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

    def _photoreal_balanced_input(
        self,
        request: ViewConditioningInput,
        *,
        style_anchor: GeneratedImage | None,
        identity_prompt: str,
    ) -> list[dict[str, str]]:
        refinement_specification = request.prompt.strip()
        design_authority = identity_prompt.strip() or "Use the approved project Design DNA."
        prompt = (
            f"AUTHORITY\n{_authority_line(request.design_freedom)}\n\n"
            f"{refinement_specification}\n\n"
            "CROSS-VIEW IDENTITY\n"
            f"{design_authority}\n"
            "The current Base RGB always wins for geometry and camera; the identity contract "
            "controls shared materials and finish. Keep common daylight unless the current view "
            "directive explicitly requests the approved VIEW-06 golden-hour photography "
            "variant.\n\n"
            "PHOTOGRAPHIC DIRECTION\nRender as a physically plausible architectural photograph."
        )
        blocks: list[dict[str, str]] = [
            {"type": "text", "text": prompt},
            {
                "type": "text",
                "text": _base_rgb_label(request.design_freedom),
            },
            _image_block(request.base_rgb),
        ]
        if request.structure_guide is not None and request.structure_guide.is_file():
            blocks.extend(
                (
                    {
                        "type": "text",
                        "text": _structure_authority_text(request.design_freedom).split(
                            "Any outlined off-site proxy"
                        )[0]
                        + (
                            " Off-site proxies may become real neighbours at their registered "
                            "locations; never extend the focus building."
                            if request.context_policy == "resolve_proxies"
                            else " Off-site context follows the context policy in the "
                            "refinement specification."
                        ),
                    },
                    _image_block(request.structure_guide),
                )
            )
        if request.role in _AERIAL_ROLES:
            blocks.extend(
                (
                    {
                        "type": "text",
                        "text": (
                            "AERIAL SITE-PLAN AUTHORITY — neutral categorical regions only. "
                            "Preserve every boundary between the site substrate, asphalt roads, "
                            "loading/service yards, parking, sidewalks, planting, gates and "
                            "buildings. Tones are not materials or output colours. Do not merge "
                            "regions or reinterpret the substrate as a concrete apron:"
                        ),
                    },
                    _neutral_semantic_block(request.semantic),
                )
            )
        if style_anchor is not None:
            blocks.extend(
                (
                    {
                        "type": "text",
                        "text": (
                            "APPROVED DESIGN MASTER — appearance identity only; never copy its "
                            "camera, layout or object positions. Keep the approved master "
                            "architecture "
                            "and materials across views within the measured envelope. Base RGB "
                            "procedural facade details are binding only in photoreal_only mode:"
                        ),
                    },
                    _generated_image_block(style_anchor),
                )
            )
        for reference in request.reference_images[:2]:
            role = _reference_role(reference)
            if role == "context_composition_guide":
                blocks.extend(
                    (
                        {
                            "type": "text",
                            "text": (
                                "CAMERA-REGISTERED CONTEXT GUIDE — resolve pale proxy volumes into "
                                "grounded, opaque, believable neighbouring industrial buildings. "
                                "Preserve their locations, count, envelope and separation from the "
                                "focus project. Do not reproduce translucent placeholders:"
                                if request.context_policy == "resolve_proxies"
                                else "CAMERA-REGISTERED CONTEXT COMPOSITION GUIDE — preserve the "
                                "focus project from Base RGB, but represent every pale proxy "
                                "volume at this exact projected location as a simple grounded "
                                "neutral translucent mass. Keep its count and spacing. Do not "
                                "turn proxies into detailed, opaque or floating buildings:"
                            ),
                        },
                        _image_block(reference),
                    )
                )
                continue
            permitted = (
                "construction detail, material response and human scale"
                if role == "factory_design_reference"
                else "industrial-estate roads, planting, atmosphere and photographic depth"
                if role == "context_realism_reference"
                else "photographic finish"
            )
            blocks.extend(
                (
                    {
                        "type": "text",
                        "text": (
                            f"REALISM REFERENCE ({role}) — use only {permitted}; never copy its "
                            "geometry, project, palette, facade motif, camera or site layout:"
                        ),
                    },
                    _image_block(reference),
                )
            )
        return blocks

    def _legacy_input(
        self,
        request: ViewConditioningInput,
        *,
        style_anchor: GeneratedImage | None,
        identity_prompt: str,
    ) -> list[dict[str, str]]:
        anchor_instruction = (
            " The final attached image is a generated STYLE ANCHOR from another approved "
            "camera of this exact project. Match only its facade language, material identity, "
            "palette, daylight, atmosphere, vegetation treatment and photographic finish. "
            "Do not copy its camera, composition, object positions or geometry; the current "
            "base RGB and passes remain the sole spatial authority."
            if style_anchor is not None
            else ""
        )
        input_order = (
            "base RGB, structural edges"
            if self._conditioning_mode is GeminiConditioningMode.MINIMAL
            else "base RGB, depth, instance ID, semantic ID, structural edges"
        )
        labeled_prompt = (
            f"{request.prompt}\n\n"
            f"{identity_prompt}\n\n"
            f"The attached images are ordered as: {input_order}, "
            "then optional approved references. Preserve the camera and all hard geometry "
            "from the base RGB; any auxiliary passes are constraints. Approved references are "
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
        input_blocks: list[dict[str, str]] = [
            {"type": "text", "text": labeled_prompt},
            {
                "type": "text",
                "text": _base_rgb_label(request.design_freedom),
            },
            _image_block(request.base_rgb),
        ]
        if self._conditioning_mode is GeminiConditioningMode.FULL:
            input_blocks.extend(
                (
                    {"type": "text", "text": "DEPTH — preserve this exact depth ordering:"},
                    _image_block(request.depth),
                    {
                        "type": "text",
                        "text": "INSTANCE ID — preserve every distinct object boundary and count:",
                    },
                    _image_block(request.instance_id),
                    {
                        "type": "text",
                        "text": (
                            "SEMANTIC ID — neutral categorical regions, never a color reference:"
                        ),
                    },
                    _neutral_semantic_block(request.semantic),
                )
            )
        input_blocks.extend(
            (
                {
                    "type": "text",
                    "text": "STRUCTURAL EDGES — do not move, remove or invent these boundaries:",
                },
                _image_block(request.edges),
            )
        )
        for index, reference in enumerate(request.reference_images, start=1):
            input_blocks.extend(
                (
                    {
                        "type": "text",
                        "text": (
                            f"REALISM REFERENCE {index} — finish quality only; no geometry, "
                            "palette or design authority:"
                        ),
                    },
                    _image_block(reference),
                )
            )
        if style_anchor is not None:
            input_blocks.append(
                {
                    "type": "text",
                    "text": "STYLE ANCHOR — shared appearance only; current-view geometry wins:",
                }
            )
            input_blocks.append(_generated_image_block(style_anchor))
        return input_blocks

    def generate(self, request: ViewConditioningInput) -> GeneratedImage:
        return self._generate(request)

    def edit(
        self,
        request: ViewEditInput,
        *,
        on_partial: Callable[[int, bytes], None] | None = None,
    ) -> tuple[GeneratedImage, ...]:
        raise ProviderError(
            "Gemini cannot repaint a masked region; set OPENAI_API_KEY so view edits "
            "run through the OpenAI images/edits endpoint"
        )

    def generate_view_set(self, request: ViewSetGenerationInput) -> GeneratedViewSet:
        """Generate every multi-view set from one project appearance authority."""

        quality_model = (
            self._settings.gemini_master_image_model or self._settings.gemini_image_model
        )
        # Production image generation is deliberately single-model. Mixing Flash and Pro inside
        # one view set produced visibly different facade language, material response and context
        # treatment between cameras. Preview still controls render resolution and review gates;
        # it must not silently downgrade the image model.
        if len(request.views) < 2:
            views = tuple(
                GeneratedView(
                    view_id=view.view_id,
                    image=self._generate(
                        view,
                        style_anchor=request.design_master,
                        identity_prompt=request.identity_prompt,
                        model=quality_model,
                    ),
                )
                for view in request.views
            )
            return GeneratedViewSet(request_id=request.request_id, views=views)

        # The overall view is the project identity authority: it contains the largest
        # observable set of roofs, facades, site access, fence and context massing.  A
        # close facade view is a poor master because the provider must invent the unseen
        # appearance of the rest of the campus.
        anchor_request = next(
            (view for view in request.views if view.view_id == request.master_view_id),
            request.views[0],
        )
        if request.design_master is None:
            anchor = self._generate(
                anchor_request,
                identity_prompt=request.identity_prompt,
                model=quality_model,
            )
            generated_by_id = {anchor_request.view_id: anchor}
        else:
            anchor = request.design_master
            generated_by_id = {}
        for view in request.views:
            if request.design_master is not None and view.view_id == request.master_view_id:
                generated_by_id[view.view_id] = anchor
            elif request.design_master is not None or view.view_id != anchor_request.view_id:
                generated_by_id[view.view_id] = self._generate(
                    view,
                    style_anchor=anchor,
                    identity_prompt=request.identity_prompt,
                    model=quality_model,
                )
        views = tuple(
            GeneratedView(view_id=view.view_id, image=generated_by_id[view.view_id])
            for view in request.views
        )
        return GeneratedViewSet(request_id=request.request_id, views=views)
