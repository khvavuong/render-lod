"""Gemini image-generation adapter with privacy-safe defaults."""

from __future__ import annotations

import base64
import io
import json
import mimetypes
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
    ViewSetGenerationInput,
)

DEFAULT_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/interactions"


class GeminiConditioningMode(str, Enum):
    """Versioned input strategies used by the controlled-realism bake-off."""

    FULL = "full"
    MINIMAL = "minimal"
    PHOTOREAL_BALANCED = "photoreal_balanced"


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
        if self._conditioning_mode is GeminiConditioningMode.PHOTOREAL_BALANCED:
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
        selected_model = model or self._settings.gemini_image_model
        payload = {
            "model": selected_model,
            "input": input_blocks,
            "store": self._settings.gemini_store_interactions,
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
            "AUTHORITY\nThe current BASE RGB is the sole spatial and camera authority.\n\n"
            f"{refinement_specification}\n\n"
            "CROSS-VIEW IDENTITY\n"
            f"{design_authority}\n"
            "The current Base RGB always wins for geometry and camera; the identity contract "
            "controls only shared materials, lighting and finish.\n\n"
            "PHOTOGRAPHIC DIRECTION\nRender as a physically plausible architectural photograph."
        )
        blocks: list[dict[str, str]] = [
            {"type": "text", "text": prompt},
            {
                "type": "text",
                "text": "BASE RGB — sole geometry, camera and composition authority:",
            },
            _image_block(request.base_rgb),
        ]
        if request.structure_guide is not None and request.structure_guide.is_file():
            blocks.extend(
                (
                    {
                        "type": "text",
                        "text": (
                            "MONOCHROME STRUCTURE AUTHORITY — preserve its project silhouette, "
                            "roof continuity, facade bay boundaries and exact authored/proposed "
                            "opening count. It is a constraint image, not a material or style "
                            "target. Any outlined off-site proxy is reserved for deterministic "
                            "post-composite; do not turn it into a detailed building:"
                        ),
                    },
                    _image_block(request.structure_guide),
                )
            )
        if style_anchor is not None:
            blocks.extend(
                (
                    {
                        "type": "text",
                        "text": (
                            "APPROVED DESIGN MASTER — appearance identity only; never copy its "
                            "camera, layout or object positions. If it conflicts with the explicit "
                            "palette or current Base RGB material regions, the palette and current "
                            "Base RGB win:"
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
                                "CAMERA-REGISTERED CONTEXT COMPOSITION GUIDE — preserve the "
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
                "text": "BASE RGB — sole camera, geometry, composition and spatial authority:",
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

    def generate_view_set(self, request: ViewSetGenerationInput) -> GeneratedViewSet:
        """Generate every multi-view set from one project appearance authority."""

        quality_model = (
            self._settings.gemini_master_image_model or self._settings.gemini_image_model
        )
        # In preview, the site master stays on Flash: it follows the registered composition and
        # approved context reference more literally. The facade master is derived from that site
        # anchor on the quality model because its construction detail propagates downstream.
        master_model = (
            quality_model
            if request.profile != "preview_fast"
            else self._settings.gemini_image_model
        )
        final_view_model = (
            self._settings.gemini_master_image_model if request.profile == "tender_final" else None
        )
        if len(request.views) < 2:
            views = tuple(
                GeneratedView(
                    view_id=view.view_id,
                    image=self._generate(
                        view,
                        style_anchor=request.design_master,
                        identity_prompt=request.identity_prompt,
                        model=(
                            quality_model
                            if request.design_master is not None
                            else master_model
                        ),
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
                model=master_model,
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
                    model=final_view_model,
                )
        views = tuple(
            GeneratedView(view_id=view.view_id, image=generated_by_id[view.view_id])
            for view in request.views
        )
        return GeneratedViewSet(request_id=request.request_id, views=views)
