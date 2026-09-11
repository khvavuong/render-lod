"""Gemini image-generation adapter with privacy-safe defaults."""

from __future__ import annotations

import base64
import io
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
                "base_rgb+design_master+one_quality_reference"
                if self._conditioning_mode is GeminiConditioningMode.PHOTOREAL_BALANCED
                else "legacy_control_pass_conditioning"
            ),
            "store_interactions": self._settings.gemini_store_interactions,
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
        payload = {
            "model": model or self._settings.gemini_image_model,
            "input": input_blocks,
            "store": self._settings.gemini_store_interactions,
            "response_format": {
                "type": "image",
                "aspect_ratio": request.aspect_ratio,
                "image_size": request.image_size,
            },
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

    @staticmethod
    def _view_direction(prompt: str) -> str:
        marker = "VIEW PURPOSE"
        position = prompt.rfind(marker)
        if position >= 0:
            return prompt[position:].strip()
        return prompt.strip()

    def _photoreal_balanced_input(
        self,
        request: ViewConditioningInput,
        *,
        style_anchor: GeneratedImage | None,
        identity_prompt: str,
    ) -> list[dict[str, str]]:
        view_direction = self._view_direction(request.prompt)
        design_authority = identity_prompt.strip() or "Use the approved project Design DNA."
        prompt = (
            "AUTHORITY\n"
            "The BASE RGB is the sole authority for camera, composition, massing, footprint, "
            "building count, roof orientation and continuity, roads, gates, fences, authored "
            "landscape zones and object placement. Its flat materials, simplified vegetation, "
            "background, lighting and CGI appearance are not visual-quality references.\n\n"
            "IMMUTABLE GEOMETRY\n"
            "Preserve those elements exactly. Do not add, delete, duplicate, move, crop or "
            "redesign primary or auxiliary buildings and site circulation. Preserve the exact "
            "visible facade elevation, authored openings, accent frames and loading doors; the "
            "Design Master never authorizes transferring its windows or entrances to this view.\n\n"
            f"DESIGN IDENTITY\n{design_authority}\n\n"
            "BOUNDED DESIGN FREEDOM\n"
            "Within the existing envelopes, add construction-plausible industrial materials, "
            "facade joints, doors, canopies, drainage, planting texture and sparse correctly "
            "scaled entourage. Treat the setting as a developed Vietnamese industrial estate "
            "with rational collector roads, curbs, drainage, divided plots, low grass and sparse "
            "street-tree rows. Keep authored context buildings as quiet neutral low-detail factory "
            "massing with reduced contrast and atmospheric fade, not transparent glass boxes. "
            "Do not invent forest, wilderness, desert, mountains, water, dense urban towers or "
            "rural scenery unless visible in the Base RGB.\n\n"
            "PHOTOGRAPHIC DIRECTION\n"
            "Create a professional real-world architectural photograph with physically plausible "
            "daylight, contact shadows, material micro-roughness, glazing reflections, atmospheric "
            "depth, subtle construction tolerances, non-uniform ground tone and restrained "
            "operational wear. Use natural vegetation variation, sensor-level grain and gentle "
            "lens falloff. The "
            "result must look captured at a real built site, not exported from architectural "
            "software. Avoid a clean BIM/CGI illustration, miniature/isometric appearance, "
            "futuristic forms, semantic colors, text and invented logos.\n\n"
            f"{view_direction}"
        )
        blocks: list[dict[str, str]] = [
            {"type": "text", "text": prompt},
            {
                "type": "text",
                "text": "BASE RGB — sole geometry, camera and composition authority:",
            },
            _image_block(request.base_rgb),
        ]
        if style_anchor is not None:
            blocks.extend(
                (
                    {
                        "type": "text",
                        "text": (
                            "APPROVED DESIGN MASTER — appearance identity only; never copy its "
                            "camera, layout or object positions:"
                        ),
                    },
                    _generated_image_block(style_anchor),
                )
            )
        if request.reference_images:
            blocks.extend(
                (
                    {
                        "type": "text",
                        "text": (
                            "REALISM REFERENCE — photographic finish only; never copy its "
                            "geometry, project, palette, facade motif, camera or site layout:"
                        ),
                    },
                    _image_block(request.reference_images[0]),
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

        if len(request.views) < 2:
            views = tuple(
                GeneratedView(
                    view_id=view.view_id,
                    image=self._generate(view, identity_prompt=request.identity_prompt),
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
                model=self._settings.gemini_master_image_model,
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
                )
        views = tuple(
            GeneratedView(view_id=view.view_id, image=generated_by_id[view.view_id])
            for view in request.views
        )
        return GeneratedViewSet(request_id=request.request_id, views=views)
