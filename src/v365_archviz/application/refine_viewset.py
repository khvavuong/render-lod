"""Generate and persist an ordered multi-view unit for one immutable design revision."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from v365_archviz.application.brand_watermark import BrandWatermark
from v365_archviz.application.refine_view import PROMPT_VERSION, RefineView
from v365_archviz.artifacts import atomic_write
from v365_archviz.domain.design import DesignDNA
from v365_archviz.domain.workflow import GenerationProfile, ViewRole, ViewSet
from v365_archviz.errors import InvalidModelError, ProviderError
from v365_archviz.providers.contracts import (
    ViewConditioningInput,
    ViewSetGenerationInput,
    ViewSetGenerativeRenderer,
)

VIEW_DIRECTIVES = {
    ViewRole.OVERALL: (
        "VIEW PURPOSE — CAMPUS MASTERPLAN: show the complete authored project parcel in one frame. "
        "Do not crop any side of the project boundary. Keep every perimeter road, external "
        "approach, entrance/security gatehouse, parking area, landscape strip and all focus "
        "buildings legible."
    ),
    ViewRole.CONTEXT: (
        "VIEW PURPOSE — CONTEXT: explain the opposite approach, adjoining roads and the "
        "relationship between the focus factory and subdued surrounding massing."
    ),
    ViewRole.HERO: (
        "VIEW PURPOSE — CLOSE HERO: retain this low, close corridor composition and emphasize a "
        "buildable facade, entrances and human scale; do not turn it into an aerial view."
    ),
    ViewRole.DETAIL: (
        "VIEW PURPOSE — LONG FACADE: retain this oblique side view so the long elevation, loading "
        "access, roof edge, drainage and facade rhythm can be assessed."
    ),
    ViewRole.OFFICE_HERO: (
        "VIEW PURPOSE — OPPOSITE CORNER: retain this distinct reverse three-quarter composition "
        "and show its access frontage; do not copy the close-hero camera."
    ),
    ViewRole.LOADING_DETAIL: (
        "VIEW PURPOSE — EXTERIOR HUMAN EYE LEVEL: keep the camera at pedestrian eye height in "
        "the open-air authored circulation space, outside every building envelope. The sky and "
        "exterior facade must remain visible. Never reinterpret this as an interior, covered hall, "
        "warehouse interior or courtyard. Show realistic scale and access without converting it "
        "to a drone view."
    ),
}


@dataclass(frozen=True, slots=True)
class RefinedViewSetArtifacts:
    request_id: str
    output_directory: Path
    manifest_path: Path
    view_count: int


def _request_id(
    model_revision: str,
    design_revision: str,
    view_set_id: str,
    profile: GenerationProfile,
    prompt: str,
    prompt_version: str,
) -> str:
    payload = "\n".join(
        (model_revision, design_revision, view_set_id, profile.value, prompt_version, prompt)
    ).encode()
    return f"gen-{hashlib.sha256(payload).hexdigest()[:16]}"


class RefineViewSet:
    def execute(
        self,
        renderer: ViewSetGenerativeRenderer,
        render_root: Path,
        output_directory: Path,
        view_set_path: Path,
        design_dna_path: Path,
        model_revision: str,
        prompt: str,
        reference_images: tuple[Path, ...] = (),
        profile: GenerationProfile = GenerationProfile.PREVIEW_FAST,
        watermark: BrandWatermark | None = None,
    ) -> RefinedViewSetArtifacts:
        view_set = ViewSet.model_validate_json(view_set_path.read_text(encoding="utf-8"))
        design = DesignDNA.model_validate_json(design_dna_path.read_text(encoding="utf-8"))
        if view_set.design_revision != design.design_revision:
            raise InvalidModelError("view set and Design DNA revisions do not match")
        requests = tuple(
            ViewConditioningInput(
                view_id=camera.view_id,
                base_rgb=render_root / camera.view_id / "base_rgb.png",
                depth=render_root / camera.view_id / "depth.png",
                instance_id=render_root / camera.view_id / "instance_id.png",
                semantic=render_root / camera.view_id / "semantic.png",
                edges=render_root / camera.view_id / "edges.png",
                prompt=f"{prompt}\n\n{VIEW_DIRECTIVES[camera.role]}",
                reference_images=reference_images,
                aspect_ratio=camera.aspect_ratio,
            )
            for camera in view_set.cameras
        )
        request_id = _request_id(
            model_revision,
            design.design_revision,
            view_set.view_set_id,
            profile,
            prompt,
            PROMPT_VERSION,
        )
        generated = renderer.generate_view_set(
            ViewSetGenerationInput(
                request_id=request_id,
                project_id=design.project_id,
                model_revision=model_revision,
                design_revision=design.design_revision,
                view_set_id=view_set.view_set_id,
                profile=profile.value,
                views=requests,
            )
        )
        expected_ids = tuple(request.view_id for request in requests)
        actual_ids = tuple(view.view_id for view in generated.views)
        if generated.request_id != request_id or actual_ids != expected_ids:
            raise ProviderError(
                "provider returned a view set with a mismatched request or view order"
            )

        artifacts = tuple(
            RefineView().execute(
                renderer,
                render_root,
                result.view_id,
                output_directory,
                prompt,
                reference_images,
                project_id=design.project_id,
                design_revision=design.design_revision,
                generated_image=result.image,
                watermark=watermark,
            )
            for result in generated.views
        )
        manifest_path = output_directory / "viewset_generation_manifest.json"
        manifest = {
            "schema_version": "1.0.0",
            "request_id": request_id,
            "project_id": design.project_id,
            "model_revision": model_revision,
            "design_revision": design.design_revision,
            "view_set_id": view_set.view_set_id,
            "profile": profile.value,
            "provider": renderer.name,
            "prompt_version": PROMPT_VERSION,
            "generation_strategy": (
                "view-03-style-anchor"
                if profile in {GenerationProfile.BASE_PRO, GenerationProfile.MARKETING_HERO}
                and any(camera.view_id == "view-03" for camera in view_set.cameras)
                else "independent-views"
            ),
            "grammar_version": design.grammar_version,
            "asset_library_version": design.asset_library_version,
            "views": [
                {
                    "view_id": camera.view_id,
                    "role": camera.role.value,
                    "manifest": str(artifact.manifest_path),
                }
                for camera, artifact in zip(view_set.cameras, artifacts, strict=True)
            ],
        }
        atomic_write(
            manifest_path,
            json.dumps(manifest, ensure_ascii=False, indent=2).encode() + b"\n",
        )
        return RefinedViewSetArtifacts(
            request_id=request_id,
            output_directory=output_directory,
            manifest_path=manifest_path,
            view_count=len(artifacts),
        )
