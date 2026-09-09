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

PROMPT_VERSION = "geometry-first-vietnam-industrial-v9-neutral-semantic"
DEFAULT_PROMPT = """Create a photorealistic professional architectural visualization of this
Vietnamese industrial project. Treat the base render and auxiliary passes as immutable spatial
geometry: preserve the exact camera, site boundary, road and sidewalk centerlines and widths,
gate/access positions, landscape-zone boundaries, footprint, massing, roof silhouette, building
count, facade rhythm, glazing and every authored opening. Never remove, reroute, widen, narrow or
invent roads, gates, yards, parking, buildings, doors, docks or landscape zones.

Make the focus factory refined but buildable and restrained: realistic symmetric low-slope
profiled-metal industrial roofs fitted inside the approved LOD100 envelope, gutters and downpipes;
disciplined cladding modules; a durable plinth; limited accent bays; shaded office glazing and a
practical entrance canopy. Preserve each approved continuous roof assembly as one uninterrupted
longitudinal roof; never subdivide it into repeated transverse roofs at source-element seams.
Avoid flat-box roof imagery, luxury-resort styling, parametric fantasy forms, excessive glass,
arbitrary curves and decorative
features without construction logic. Use a coherent material palette across every view.

COLOR-LOCK RULE: use only the exact approved Design DNA palette. Every factory roof must keep the
same approved light-neutral metal finish in every view. Accent elements must use only the approved
accent color. Do not introduce red, orange, purple, cyan, electric blue or a dark/black roof unless
that exact color is explicitly present in the approved palette. In particular, red pixels in the
semantic-ID image mean "focus factory" only: they are not a material or facade color and no trace
of semantic red may survive in the photorealistic output.

REFERENCE-USAGE RULE: any attached reference is a non-binding realism sample. Borrow only its
photographic credibility, material response, construction-detail density, plausible finish and
human/vehicle scale. Never copy its color palette, facade motif, roof form, massing, site layout,
landscape layout, surrounding land use, camera or project-specific objects. The approved Design
DNA and geometry passes always take precedence.

Avoid the pristine CAD/CG look through subtle, physically plausible roughness and tonal variation,
panel joints, flashings and restrained signs of operation. Keep the project clean and
bid-presentation ready rather than artificially perfect or theatrically weathered. Entourage must
be sparse, correctly scaled and operationally plausible for an industrial site.

PHOTOREALISM RULE: the result must read as a professional full-frame architectural photograph,
not a clean 3D illustration. Use physically plausible global illumination, contact shadows,
light-neutral metal micro-roughness, glazing reflections, atmospheric perspective and restrained
sensor-like detail. Asphalt and concrete require fine aggregate variation, realistic joints,
drainage edges, curbs and very subtle operational wear without changing any authored road shape.
Planting must have non-repeating species/height variation, believable density, ground contact and
shadows; vehicles and people must remain correctly scaled. Keep the exact same sun direction,
clear-morning weather, white balance, exposure family, material response and color grade across
the entire six-view set. Avoid plastic vegetation, tiled/repeated trees, perfectly uniform paving,
over-smoothed surfaces, HDR halos, excessive sharpening, miniature/tilt-shift appearance and
generic CGI cleanliness.

Convert authored landscape-zone geometry into continuous, climate-appropriate Vietnamese planting
without changing its footprint. Keep traffic and fire-access routes fully legible and unobstructed.
CONTEXT-BUILDING RULE: render a context building only where its geometry exists in the base render
and its pixels are explicitly marked as context in the semantic-ID pass. Never extrapolate, mirror,
clone or fill unmarked background with blocks. For approved context geometry, use quiet pale
translucent massing: preserve exact size and position, add no facade design, and keep attention on
focus buildings. Context-landscape pixels may become soft distant tree belts, but must remain
visually secondary and may not spill into the protected project site.
Add sparse entourage only where it cannot hide protected architecture or circulation.
Use physically plausible daylight and materials, premium bid-presentation quality, no text, no
logos or aerial labels. Semantic-pass annotation colors must never leak into the final image;
cyan, magenta or electric-blue edge fringes are prohibited unless explicitly present in the
approved material palette."""


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
            "semantic": view_directory / "semantic.png",
            "edges": view_directory / "edges.png",
        }
        missing = [name for name, path in inputs.items() if not path.is_file()]
        missing.extend(f"reference:{path.name}" for path in reference_images if not path.is_file())
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
                semantic=inputs["semantic"],
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
