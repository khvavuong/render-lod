"""Generate and persist an ordered multi-view unit for one immutable design revision."""

from __future__ import annotations

import hashlib
import json
import mimetypes
from dataclasses import dataclass
from pathlib import Path

from v365_archviz.application.brand_watermark import BrandWatermark
from v365_archviz.application.refine_view import PROMPT_VERSION, RefineView
from v365_archviz.artifacts import atomic_write
from v365_archviz.domain.design import DesignDNA
from v365_archviz.domain.workflow import Camera, GenerationProfile, ViewRole, ViewSet
from v365_archviz.errors import InvalidModelError, ProviderError
from v365_archviz.providers.contracts import (
    GeneratedImage,
    ImageProviderCapabilities,
    ViewConditioningInput,
    ViewSetGenerationInput,
    ViewSetGenerativeRenderer,
)

VIEW_DIRECTIVES = {
    ViewRole.OVERALL: (
        "VIEW PURPOSE — CAMPUS MASTERPLAN: show the complete authored project parcel in one frame. "
        "Do not crop any side of the project boundary. Keep every perimeter road, external "
        "approach, entrance/security gatehouse, parking area, landscape strip and all focus "
        "buildings legible. Make it read as a real high-resolution drone photograph with natural "
        "atmospheric depth, not an isometric masterplan rendering."
    ),
    ViewRole.CONTEXT: (
        "VIEW PURPOSE — CONTEXT: explain the opposite approach, adjoining roads and the "
        "relationship between the focus factory and subdued surrounding massing. Use credible "
        "drone optics and distance haze from a real industrial estate."
    ),
    ViewRole.HERO: (
        "VIEW PURPOSE — CLOSE HERO: retain this low, close corridor composition and emphasize a "
        "buildable facade, entrances and human scale; do not turn it into an aerial view. Use the "
        "natural perspective and exposure of a full-frame architectural photograph."
    ),
    ViewRole.DETAIL: (
        "VIEW PURPOSE — LONG FACADE: retain this oblique side view so the long elevation, loading "
        "access, roof edge, drainage and facade rhythm can be assessed. Show real cladding, seals, "
        "joints and surface response rather than pristine procedural panels."
    ),
    ViewRole.OFFICE_HERO: (
        "VIEW PURPOSE — OPPOSITE CORNER: retain this distinct reverse three-quarter composition "
        "and show its access frontage; do not copy the close-hero camera. Use plausible ground "
        "texture, contact and full-frame architectural-photo optics."
    ),
    ViewRole.LOADING_DETAIL: (
        "VIEW PURPOSE — EXTERIOR HUMAN EYE LEVEL: keep the camera at pedestrian eye height in "
        "the open-air authored circulation space, outside every building envelope. The sky and "
        "exterior facade must remain visible. Never reinterpret this as an interior, covered hall, "
        "warehouse interior or courtyard. Show realistic scale and access without converting it "
        "to a drone view. Use a 28-35 mm documentary architectural-photo character at 1.65 m eye "
        "height, with natural surface variation and no miniature look."
    ),
}


@dataclass(frozen=True, slots=True)
class RefinedViewSetArtifacts:
    request_id: str
    output_directory: Path
    manifest_path: Path
    identity_pack_path: Path
    view_count: int


def _identity_contract(design: DesignDNA) -> tuple[dict[str, object], str]:
    """Create the immutable appearance rules shared by every camera in a view set."""

    palette = design.material_palette.model_dump()
    environment = design.environment.model_dump()
    roof_assemblies = [
        {
            "assembly_id": assembly.assembly_id,
            "building_ids": list(assembly.building_ids),
            "roof_type": assembly.roof.roof_type,
            "ridge_orientation": assembly.roof.ridge_orientation,
        }
        for assembly in design.roof_assemblies
    ]
    solar_panel_building_ids = [
        building.building_id for building in design.buildings if building.roof.solar_panels
    ]
    solar_policy = (
        "approved only on " + ", ".join(solar_panel_building_ids)
        if solar_panel_building_ids
        else "prohibited on every building"
    )
    focus_facades = [
        facade
        for building in design.buildings
        if building.treatment.value == "focus"
        for facade in building.facades
    ]
    entrance_facades = [facade for facade in focus_facades if facade.office_entrance is not None]
    loading_dock_count = sum(len(facade.loading_docks) for facade in focus_facades)
    panel_modules = sorted({facade.panel_module_m for facade in focus_facades})
    facade_grammar = (
        f"cladding module={','.join(f'{value:g}m' for value in panel_modules) or 'model-derived'}; "
        f"office entrance bays={len(entrance_facades)}; loading docks={loading_dock_count}. "
        "Confine office glazing and feature fins to authored entrance/design-detail bays; do not "
        "spread an office glazing ratio across plain factory elevations or shed end walls."
    )
    contract: dict[str, object] = {
        "project_id": design.project_id,
        "design_revision": design.design_revision,
        "design_language": design.design_language.model_dump(),
        "material_palette": palette,
        "environment": environment,
        "presentation": design.presentation.model_dump(),
        "roof_assemblies": roof_assemblies,
        "solar_panel_building_ids": solar_panel_building_ids,
    }
    prompt = (
        "PROJECT DESIGN IDENTITY — immutable across all six cameras: "
        f"style={design.design_language.style}; "
        f"materials={design.design_language.primary_material}, "
        f"{design.design_language.secondary_material}, "
        f"{design.design_language.office_material}; "
        f"palette={', '.join(str(value) for value in palette.values())}; "
        f"daylight={environment['time']} {environment['weather']}, "
        f"white balance={environment['white_balance_k']}K. "
        f"landscape={design.presentation.landscape_character}; "
        f"paving={design.presentation.paving_character}; "
        f"decor={design.design_preferences.decor_level.value}; "
        f"user direction={design.design_preferences.creative_prompt or 'none'}. "
        f"solar panels={solar_policy}. "
        f"facade grammar={facade_grammar} "
        "Use one restrained, buildable facade family, roof finish, fence/gate family, landscape "
        "vocabulary, weather, exposure and color grade throughout the view set. The Design Master "
        "controls appearance only; each current base render controls geometry and camera."
    )
    return contract, prompt


def _select_master_view_id(render_root: Path, cameras: tuple[Camera, ...]) -> str:
    """Choose an overview with useful site coverage without relying on a view identifier."""

    evidence: dict[str, dict[str, object]] = {}
    report_path = render_root / "conditioning_qa.json"
    if report_path.is_file():
        try:
            document = json.loads(report_path.read_text(encoding="utf-8"))
            evidence = {
                str(item["view_id"]): item
                for item in document.get("views", [])
                if isinstance(item, dict) and item.get("view_id")
            }
        except (OSError, json.JSONDecodeError, KeyError, TypeError):
            evidence = {}

    role_priority = {
        ViewRole.OVERALL: 6.0,
        ViewRole.CONTEXT: 5.0,
        ViewRole.DETAIL: 4.0,
        ViewRole.OFFICE_HERO: 3.0,
        ViewRole.HERO: 2.0,
        ViewRole.LOADING_DETAIL: 1.0,
    }

    def score(camera: Camera) -> tuple[float, str]:
        view_id = camera.view_id
        role = camera.role
        item = evidence.get(view_id, {})
        values = (
            item.get(name)
            for name in (
                "focus_coverage",
                "circulation_coverage",
                "context_coverage",
            )
        )
        coverage = sum(float(value) for value in values if isinstance(value, (int, float)))
        passed = 1.0 if item.get("status") == "pass" else 0.0
        return role_priority.get(role, 0.0) * 10.0 + passed + coverage, view_id

    return max(cameras, key=score).view_id


def _visible_facade_directive(design: DesignDNA, camera: Camera) -> str:
    """Project the camera direction into a general facade-side design constraint."""

    delta_x = camera.position[0] - camera.target[0]
    delta_y = camera.position[1] - camera.target[1]
    if abs(delta_x) >= abs(delta_y):
        direction = "east" if delta_x >= 0 else "west"
    else:
        direction = "north" if delta_y >= 0 else "south"
    facades = [
        facade
        for building in design.buildings
        if building.treatment.value == "focus"
        for facade in building.facades
        if facade.surface_id.rsplit(":", maxsplit=1)[-1] == direction
    ]
    entrance_count = sum(facade.office_entrance is not None for facade in facades)
    dock_count = sum(len(facade.loading_docks) for facade in facades)
    return (
        f"PRIMARY VISIBLE FACADE — {direction}: approved generated office entrance bays="
        f"{entrance_count}, approved generated loading docks={dock_count}. Preserve every opening "
        "already visible in the Base RGB, but do not add or copy any extra entrance, dock, large "
        "glazed bay or feature frame from the Design Master onto this facade."
    )


def _request_id(
    model_revision: str,
    design_revision: str,
    view_set_id: str,
    profile: GenerationProfile,
    prompt: str,
    prompt_version: str,
    provider_variant: str,
    selected_view_ids: tuple[str, ...],
    reference_hashes: tuple[str, ...],
) -> str:
    payload = "\n".join(
        (
            model_revision,
            design_revision,
            view_set_id,
            profile.value,
            prompt_version,
            provider_variant,
            ",".join(selected_view_ids),
            ",".join(reference_hashes),
            prompt,
        )
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
        view_ids: tuple[str, ...] = (),
        approved_master_path: Path | None = None,
        approved_master_view_id: str | None = None,
    ) -> RefinedViewSetArtifacts:
        view_set = ViewSet.model_validate_json(view_set_path.read_text(encoding="utf-8"))
        design = DesignDNA.model_validate_json(design_dna_path.read_text(encoding="utf-8"))
        if view_set.design_revision != design.design_revision:
            raise InvalidModelError("view set and Design DNA revisions do not match")
        known_view_ids = {camera.view_id for camera in view_set.cameras}
        unknown_view_ids = set(view_ids) - known_view_ids
        if unknown_view_ids:
            raise InvalidModelError(f"unknown benchmark view IDs: {sorted(unknown_view_ids)}")
        selected_cameras = tuple(
            camera for camera in view_set.cameras if not view_ids or camera.view_id in view_ids
        )
        if not selected_cameras:
            raise InvalidModelError("view-set selection cannot be empty")
        design_master: GeneratedImage | None = None
        if approved_master_path is not None:
            if not approved_master_path.is_file():
                raise InvalidModelError(
                    f"approved Design Master does not exist: {approved_master_path}"
                )
            media_type = mimetypes.guess_type(approved_master_path.name)[0]
            if not media_type or not media_type.startswith("image/"):
                raise InvalidModelError("approved Design Master must be an image")
            design_master = GeneratedImage(
                content=approved_master_path.read_bytes(),
                media_type=media_type,
                provider_request_id=None,
            )
        requests = tuple(
            ViewConditioningInput(
                view_id=camera.view_id,
                base_rgb=render_root / camera.view_id / "base_rgb.png",
                depth=render_root / camera.view_id / "depth.png",
                instance_id=render_root / camera.view_id / "instance_id.png",
                semantic=render_root / camera.view_id / "semantic.png",
                edges=render_root / camera.view_id / "edges.png",
                prompt=(
                    f"{prompt}\n\n{VIEW_DIRECTIVES[camera.role]}\n"
                    f"{_visible_facade_directive(design, camera)}"
                ),
                structure_guide=render_root / camera.view_id / "structure_guide.png",
                reference_images=reference_images,
                aspect_ratio=camera.aspect_ratio,
                image_size=("1K" if profile is GenerationProfile.PREVIEW_FAST else "2K"),
            )
            for camera in selected_cameras
        )
        request_id = _request_id(
            model_revision,
            design.design_revision,
            view_set.view_set_id,
            profile,
            prompt,
            PROMPT_VERSION,
            json.dumps(
                {"name": renderer.name, **getattr(renderer, "provenance", {})},
                sort_keys=True,
                separators=(",", ":"),
            ),
            tuple(camera.view_id for camera in selected_cameras),
            (
                *(hashlib.sha256(path.read_bytes()).hexdigest() for path in reference_images),
                *(
                    (hashlib.sha256(approved_master_path.read_bytes()).hexdigest(),)
                    if approved_master_path is not None
                    else ()
                ),
            ),
        )
        if approved_master_view_id is not None and approved_master_view_id not in known_view_ids:
            raise InvalidModelError(
                f"unknown approved Design Master view ID: {approved_master_view_id}"
            )
        master_view_id = approved_master_view_id or _select_master_view_id(
            render_root,
            view_set.cameras if approved_master_path is not None else selected_cameras,
        )
        identity_contract, identity_prompt = _identity_contract(design)
        generated = renderer.generate_view_set(
            ViewSetGenerationInput(
                request_id=request_id,
                project_id=design.project_id,
                model_revision=model_revision,
                design_revision=design.design_revision,
                view_set_id=view_set.view_set_id,
                profile=profile.value,
                views=requests,
                identity_prompt=identity_prompt,
                master_view_id=master_view_id,
                design_master=design_master,
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
        master_image = design_master or next(
            view.image for view in generated.views if view.view_id == master_view_id
        )
        identity_pack_path = output_directory / "design_identity_pack.json"
        identity_pack = {
            "schema_version": "1.0.0",
            **identity_contract,
            "provider": renderer.name,
            "provider_configuration": getattr(renderer, "provenance", {}),
            "master_view_id": master_view_id,
            "master_sha256": hashlib.sha256(master_image.content).hexdigest(),
            "master_provider_request_id": master_image.provider_request_id,
            "approved_master_ref": (
                str(approved_master_path) if approved_master_path is not None else None
            ),
            "authority_order": [
                "current_view_base_geometry",
                "design_master_appearance",
                "realism_references_finish_only",
            ],
        }
        atomic_write(
            identity_pack_path,
            json.dumps(identity_pack, ensure_ascii=False, indent=2).encode() + b"\n",
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
            "provider_configuration": getattr(renderer, "provenance", {}),
            "prompt_version": PROMPT_VERSION,
            "generation_strategy": (
                "design-master-sequential"
                if len(requests) >= 2
                and getattr(
                    renderer, "capabilities", ImageProviderCapabilities()
                ).supports_multi_reference
                else "identity-contract-independent"
                if len(requests) >= 2
                else "single-view"
            ),
            "conditioning_policy": getattr(renderer, "provenance", {}).get(
                "input_policy", "provider_defined"
            ),
            "reference_roles": ["quality_only" for _ in reference_images],
            "design_identity_pack": str(identity_pack_path),
            "master_view_id": master_view_id,
            "generated_view_ids": [camera.view_id for camera in selected_cameras],
            "resumed_from_approved_master": approved_master_path is not None,
            "approved_master_ref": (
                str(approved_master_path) if approved_master_path is not None else None
            ),
            "master_sha256": hashlib.sha256(master_image.content).hexdigest(),
            "grammar_version": design.grammar_version,
            "asset_library_version": design.asset_library_version,
            "views": [
                {
                    "view_id": camera.view_id,
                    "role": camera.role.value,
                    "manifest": str(output_directory / camera.view_id / "generation_manifest.json"),
                }
                for camera in view_set.cameras
                if (output_directory / camera.view_id / "generation_manifest.json").is_file()
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
            identity_pack_path=identity_pack_path,
            view_count=len(artifacts),
        )
