"""Refine one approved conditioning pack through a generative renderer."""

from __future__ import annotations

import hashlib
import io
import json
import mimetypes
from dataclasses import asdict, dataclass
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from v365_archviz.application.brand_watermark import BrandWatermark
from v365_archviz.artifacts import atomic_write
from v365_archviz.errors import InvalidModelError, ProviderError
from v365_archviz.providers.contracts import (
    GeneratedImage,
    GenerativeRenderer,
    ImageProviderCapabilities,
    ViewConditioningInput,
)

PROMPT_VERSION = "layered-authority-v4"
DEFAULT_PROMPT = """Create a photorealistic professional architectural visualization of this
Vietnamese industrial project. Treat the base render and auxiliary passes as immutable spatial
geometry: preserve the exact camera, site boundary, authored road and sidewalk centerlines and
widths, gate/access positions, landscape-zone boundaries, footprint, massing, roof silhouette,
building count, facade rhythm, glazing and every authored opening. Never remove, reroute, widen or
narrow authored roads, gates, yards, parking, buildings, doors, docks or landscape zones. New
low-detail context infrastructure is allowed only in explicitly FREE off-site pixels and must
never cross or alter the authored project/site geometry.

Make the focus factory refined but buildable and restrained: realistic symmetric low-slope
profiled-metal industrial roofs fitted inside the approved LOD100 envelope, gutters and downpipes;
disciplined cladding modules; a durable plinth; limited accent bays; shaded office glazing and a
practical entrance canopy. Preserve each approved continuous roof assembly as one uninterrupted
longitudinal roof; never subdivide it into repeated transverse roofs at source-element seams.
Avoid flat-box roof imagery, luxury-resort styling, parametric fantasy forms, excessive glass,
arbitrary curves and decorative
features without construction logic. Use a coherent material palette across every view.

COLOR-ROLE LOCK: use the exact approved Design DNA palette as a material specification, not a loose
color suggestion. Apply roof to the continuous profiled-metal roof; primary to the dominant
focus-factory wall cladding; secondary to plinths, structural grids, eaves, flashings, dock frames
and doors; boundary to fence posts, infill and gate metalwork; glass only to authored glazing;
accent only to a small entrance/signage datum occupying
no more than roughly 8 percent of the focus facade; paving only to authored roads and yards. Keep
these five role assignments, hue families, finish roughness and relative prominence identical in
all six views despite distance, haze and exposure. Never collapse a user-selected chromatic primary
or secondary back to generic white/black. Do not introduce red, orange, purple, cyan or electric
blue unless that exact color is explicitly present in the approved palette. Red semantic-ID pixels
mean "focus factory" only and must never survive as material color.

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
SITE-ACCESS RULE: preserve every authored perimeter/external road and every approach to the site.
Where a main-entrance semantic element or security gatehouse touches an authored boundary road,
render a plausible controlled gate opening and guardhouse at that exact location and nowhere else.
Keep all authored entrance locations simultaneously visible when the camera framing contains them.
Never relocate an entrance or block it with planting, vehicles or invented construction. Draw a
perimeter fence only where boundary geometry is explicitly present in the conditioning passes.
Keep every visible fence run continuous except at an authored gate opening; retain its plinth,
posts and rails instead of replacing it with planting. Use one buildable boundary family throughout:
a low durable concrete plinth where supported by geometry, regular galvanized or secondary-color
steel posts, and restrained vertical-bar or welded-mesh infill. Read the gate as a controlled
vehicular entrance connected to the authored internal and external roads, with its exact opening
preserved. Use the same gate leaf count, post spacing, height, secondary-color metal finish and
fence connection in every view. The gate must be structurally anchored to fence posts; never render
a floating accent rectangle, ceremonial portal, disconnected frame or arbitrary duplicate gate.
UTILITY-BUILDING RULE: every authored utility/auxiliary mass is an opaque, secondary support
building on the subject site. Preserve its exact footprint, height, service door and ventilation
details. Give it restrained durable industrial finishes; never turn it into another main shed,
office pavilion, translucent context block, decorative landmark or landscaping.
CONTEXT-BUILDING RULE: render a context building only where its geometry exists in the base render
and its pixels are explicitly marked as context in the semantic-ID pass. Never extrapolate, mirror,
clone or fill unmarked background with blocks. For approved context geometry, use quiet pale
frosted translucent conceptual massing with credible ground contact, soft shadows, low contrast
and atmospheric fade: preserve exact size and position, add no facade design, and keep attention
on focus buildings. It must read as an intentional neutral planning proxy, never glass architecture,
ghost buildings or floating blocks. CONTEXT SETTING RULE: this is a developed Vietnamese industrial
park, not a forest or rural wilderness. Complete FREE off-site pixels only with photographic sky,
atmospheric continuity and a subdued neutral ground continuation; never invent buildings, roads,
plots, fences or other site geometry there. Render industrial-estate roads, curbs, drainage,
divided plots, low grass, street-tree rows and secondary warehouses only where their geometry is
visible in the Base RGB or semantic passes. Trees must remain limited to authored verges, rows,
setbacks and belts; they must not form continuous dense canopy. Context must remain visually
secondary and may not spill into the protected project site.
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


def _reference_role(path: Path) -> str:
    metadata_path = path.parent / "metadata.json"
    try:
        document = json.loads(metadata_path.read_text(encoding="utf-8"))
        role = document.get("role")
    except (OSError, json.JSONDecodeError):
        role = None
    return str(role) if role else "quality_only"


def _composite_context_proxy(content: bytes, media_type: str, overlay_path: Path) -> bytes:
    """Restore the deterministic planning-context layer after generative refinement."""

    with Image.open(io.BytesIO(content)) as generated_source:
        generated = generated_source.convert("RGBA")
    with Image.open(overlay_path) as overlay_source:
        overlay = overlay_source.convert("RGBA")
    if overlay.size != generated.size:
        overlay = overlay.resize(generated.size, Image.Resampling.LANCZOS)
    result = Image.alpha_composite(generated, overlay)
    buffer = io.BytesIO()
    if media_type == "image/jpeg":
        result.convert("RGB").save(buffer, format="JPEG", quality=95, optimize=True)
    else:
        result.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


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
        watermark: BrandWatermark | None = None,
        effective_provider_model: str | None = None,
    ) -> RefinedViewArtifacts:
        view_directory = render_root / view_id
        inputs = {
            "base_rgb": view_directory / "base_rgb.png",
            "depth": view_directory / "depth.png",
            "instance_id": view_directory / "instance_id.png",
            "semantic": view_directory / "semantic.png",
            "edges": view_directory / "edges.png",
        }
        structure_guide = view_directory / "structure_guide.png"
        if structure_guide.is_file():
            inputs["structure_guide"] = structure_guide
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
                structure_guide=inputs.get("structure_guide"),
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
        provider_source_path = target / f"provider_source{extension}"
        provider_raw_path = target / f"provider_raw{extension}"
        manifest_path = target / "generation_manifest.json"
        context_proxy_path = view_directory / "context_proxy_rgba.png"
        final_content = generated.content
        if context_proxy_path.is_file():
            atomic_write(provider_raw_path, generated.content)
            final_content = _composite_context_proxy(
                generated.content, generated.media_type, context_proxy_path
            )
        if watermark is None:
            atomic_write(image_path, final_content)
        else:
            atomic_write(provider_source_path, final_content)
            watermark.apply_image(provider_source_path, image_path)
        manifest = {
            "schema_version": "1.0.0",
            "view_id": view_id,
            "project_id": project_id,
            "design_revision": design_revision,
            "provider": renderer.name,
            "provider_capabilities": asdict(
                getattr(renderer, "capabilities", ImageProviderCapabilities())
            ),
            "provider_configuration": getattr(renderer, "provenance", {}),
            "effective_provider_model": effective_provider_model,
            "provider_request_id": generated.provider_request_id,
            "prompt_version": PROMPT_VERSION,
            "inputs": {
                **{name: _sha256(path) for name, path in inputs.items()},
                **{
                    f"reference_{index:02d}": _sha256(path)
                    for index, path in enumerate(reference_images, start=1)
                },
                **(
                    {"context_proxy_rgba": _sha256(context_proxy_path)}
                    if context_proxy_path.is_file()
                    else {}
                ),
            },
            "input_roles": {
                "base_rgb": "geometry_authority",
                "depth": "qa_evidence_only",
                "instance_id": "qa_evidence_only",
                "semantic": "qa_evidence_only",
                "edges": "qa_evidence_only",
                **(
                    {"structure_guide": "optional_provider_control"}
                    if "structure_guide" in inputs
                    else {}
                ),
                **{
                    f"reference_{index:02d}": _reference_role(path)
                    for index, path in enumerate(reference_images, start=1)
                },
                **(
                    {"context_proxy_rgba": "deterministic_final_overlay"}
                    if context_proxy_path.is_file()
                    else {}
                ),
            },
            "output": {
                "media_type": generated.media_type,
                "provider_raw_sha256": hashlib.sha256(generated.content).hexdigest(),
                "provider_source_sha256": hashlib.sha256(final_content).hexdigest(),
                "sha256": _sha256(image_path),
                "brand_watermark": watermark is not None,
                "context_proxy_composited": context_proxy_path.is_file(),
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
