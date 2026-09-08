"""Refine one approved conditioning pack through a generative renderer."""

from __future__ import annotations

import hashlib
import io
import json
import mimetypes
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from v365_archviz.artifacts import atomic_write
from v365_archviz.errors import InvalidModelError, ProviderError
from v365_archviz.providers.contracts import (
    GeneratedImage,
    GenerativeRenderer,
    ViewConditioningInput,
)

PROMPT_VERSION = "geometry-first-refinement-v2"
DEFAULT_PROMPT = """Create a photorealistic professional architectural visualization of this
project. Treat the base render as immutable design geometry: preserve the
exact camera, footprint, massing, roofs, building count, facade panel rhythm, office glazing,
and every authored opening. Do not invent, remove, resize, or relocate buildings, doors, docks,
windows, or roads. Follow the supplied project Design DNA and approved references for visual
language and quality only. Add entourage only where it does not occlude protected architecture.
Do not add site features such as pools, ponds, roads, roofs, canopies, or rooftop equipment unless
they are explicitly present in the base geometry or approved Design DNA. Do not reinterpret a
colored conditioning surface as water or vegetation.
Use physically plausible light and materials, premium marketing archviz quality, no text, no
logos, and no aerial labels."""


@dataclass(frozen=True, slots=True)
class RefinedViewArtifacts:
    image_path: Path
    manifest_path: Path
    provider_request_id: str | None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class RefineView:
    def execute(
        self,
        renderer: GenerativeRenderer,
        render_root: Path,
        view_id: str,
        output_directory: Path,
        prompt: str = DEFAULT_PROMPT,
        reference_images: tuple[Path, ...] = (),
        project_id: str | None = None,
        design_revision: str | None = None,
        generated_image: GeneratedImage | None = None,
    ) -> RefinedViewArtifacts:
        view_directory = render_root / view_id
        inputs = {
            "base_rgb": view_directory / "base_rgb.png",
            "depth": view_directory / "depth.png",
            "instance_id": view_directory / "instance_id.png",
            "edges": view_directory / "edges.png",
        }
        missing = [name for name, path in inputs.items() if not path.is_file()]
        missing.extend(
            f"reference:{path.name}" for path in reference_images if not path.is_file()
        )
        if missing:
            raise InvalidModelError(
                f"conditioning pack {view_id} is missing: {', '.join(sorted(missing))}"
            )
        generated = generated_image or renderer.generate(
            ViewConditioningInput(
                view_id=view_id,
                base_rgb=inputs["base_rgb"],
                depth=inputs["depth"],
                instance_id=inputs["instance_id"],
                edges=inputs["edges"],
                prompt=prompt,
                reference_images=reference_images,
            )
        )
        try:
            with Image.open(io.BytesIO(generated.content)) as image:
                image.verify()
        except (UnidentifiedImageError, OSError) as exc:
            raise ProviderError("renderer returned an invalid image") from exc

        extension = mimetypes.guess_extension(generated.media_type) or ".png"
        target = output_directory / view_id
        image_path = target / f"refined{extension}"
        manifest_path = target / "generation_manifest.json"
        atomic_write(image_path, generated.content)
        manifest = {
            "schema_version": "1.0.0",
            "view_id": view_id,
            "project_id": project_id,
            "design_revision": design_revision,
            "provider": renderer.name,
            "provider_request_id": generated.provider_request_id,
            "prompt_version": PROMPT_VERSION,
            "inputs": {
                **{name: _sha256(path) for name, path in inputs.items()},
                **{
                    f"reference_{index:02d}": _sha256(path)
                    for index, path in enumerate(reference_images, start=1)
                },
            },
            "output": {
                "media_type": generated.media_type,
                "sha256": hashlib.sha256(generated.content).hexdigest(),
            },
        }
        atomic_write(
            manifest_path,
            json.dumps(manifest, ensure_ascii=False, indent=2).encode() + b"\n",
        )
        return RefinedViewArtifacts(
            image_path=image_path,
            manifest_path=manifest_path,
            provider_request_id=generated.provider_request_id,
        )
