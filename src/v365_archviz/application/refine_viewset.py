"""Generate and persist an ordered multi-view unit for one immutable design revision."""

from __future__ import annotations

import hashlib
import json
import mimetypes
from dataclasses import dataclass
from pathlib import Path

from v365_archviz.application.brand_watermark import BrandWatermark
from v365_archviz.application.refine_view import (
    PROMPT_VERSION,
    RefineView,
    build_context_composition_guide,
)
from v365_archviz.artifacts import atomic_write
from v365_archviz.domain.design import DesignDNA
from v365_archviz.domain.style_pack import StylePack
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
        "VIEW PURPOSE — HERO AERIAL OBLIQUE: this is the primary bid cover. Preserve the approved "
        "drone camera and three-quarter azimuth so two principal facades and roughly 70-80% of the "
        "authored site remain legible. Explain the masterplan, continuous roof assemblies, "
        "massing, "
        "palette, landscape and relationships between buildings. Never flatten it into a frontal "
        "elevation, crop the site into one facade or invent off-site development."
    ),
    ViewRole.CONTEXT: (
        "VIEW PURPOSE — MAIN ENTRANCE / ARRIVAL: preserve this pedestrian-eye approach along the "
        "authored vehicle path from outside the main gate. Clearly show the truck-capable opening, "
        "connected fence, entrance identity zone, office block, facade recognition, landscape and "
        "arrival axis. Keep the 28-35 mm documentary perspective; never make the gate decorative, "
        "too narrow, blocked or detached from the road. Do not invent readable signage or logos. "
        "At this distance every surface is read up close: replace the flat conditioning render "
        "with real construction — profiled panel ribs and joints, fixings, gutters and "
        "downpipes, plinth texture, road kerbs, drainage, paving joints, light wear and natural "
        "planting — at the photographic quality of the approved Design Master."
    ),
    ViewRole.HERO: (
        "VIEW PURPOSE — LOGISTICS / OPERATION: prove that the project can operate. Preserve the "
        "authored loading facade, truck apron, industrial shutter or sectional doors, docks, "
        "canopies, bollards, turning clearance and service circulation. Add only sparse correctly "
        "scaled operational trucks, pallets and workers where they do not hide doors or geometry. "
        "This is a credible working yard, not a showroom, residential street or office frontage."
    ),
    ViewRole.DETAIL: (
        "VIEW PURPOSE — SECONDARY AERIAL / MASSING FROM ANOTHER SIDE: preserve this drone "
        "position, which looks at the project from a different bearing than the Hero Aerial, not "
        "a small pan from it. Confirm the facades seen from this side, internal roads, setbacks, "
        "planting, utility/service areas and the relationship between all authored masses. Match "
        "VIEW-01's photographic detail, material texture, daylight and colour grade exactly: this "
        "is the same photo shoot from another drone position, never a softer or more rendered "
        "image. Keep the same project identity and expose inconsistencies rather than "
        "redesigning unseen sides."
    ),
    ViewRole.OFFICE_HERO: (
        "VIEW PURPOSE — ARCHITECTURAL DETAIL / OFFICE FACADE: preserve this close eye-level "
        "composition of the best authored office entrance ensemble; when no office entrance exists "
        "in the model, use the strongest authored industrial door/canopy facade ensemble instead. "
        "Show glazing only where authored, panel modules, entrance or industrial door, plinth, "
        "facade depth and restrained landscape at believable construction scale. It need not show "
        "the whole factory. Do not invent an office block or spread office glazing into plain bays."
    ),
    ViewRole.LOADING_DETAIL: (
        "VIEW PURPOSE — HUMAN-SCALE / GOLDEN-HOUR HERO: preserve the low human-scale oblique "
        "camera and all design geometry, changing only photography DNA. This view explicitly "
        "overrides the shared daylight environment: use credible late-afternoon golden light, a "
        "low warm "
        "sun, long physically plausible shadows, restrained warm loading/entrance lights and "
        "a modest number of people and vehicles. Keep facade materials neutral and technically "
        "legible; no cinematic fantasy colours, wet-road spectacle or night-time darkness."
    ),
    ViewRole.CUSTOM: (
        "VIEW PURPOSE — USER-COMPOSED VIEW: the client placed this camera deliberately. Preserve "
        "its exact position, height, direction and lens, and photograph whatever authored "
        "architecture, site and landscape it frames with the same approved design identity as "
        "the Design Master. Do not re-frame it into a standard hero, aerial or entrance view, and "
        "do not invent architecture outside the authored geometry."
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
    loading_door_families = sorted(
        {
            (
                dock.door_type,
                dock.threshold_type,
                round(dock.width_m, 2),
                round(dock.clear_height_m, 2),
                round(dock.canopy_projection_m, 2),
            )
            for facade in focus_facades
            for dock in facade.loading_docks
        }
    )
    panel_modules = sorted({facade.panel_module_m for facade in focus_facades})
    articulation = focus_facades[0].articulation if focus_facades else None
    articulation_grammar = (
        f"plinth={articulation.plinth_height_m:g}m; top band="
        f"{articulation.parapet_band_height_m:g}m; feature-frame depth="
        f"{articulation.feature_frame_depth_m:g}m; entrance canopy="
        f"{articulation.entrance_canopy_projection_m:g}m; vertical fins="
        f"{articulation.vertical_fin_count}; accent interval="
        f"{articulation.accent_bay_interval}; clerestory="
        f"{articulation.clerestory_band_height_m:g}m at sill ratio "
        f"{articulation.clerestory_sill_ratio:g}; biophilic trellis interval="
        f"{articulation.biophilic_bay_interval} bays, width="
        f"{articulation.biophilic_bay_width_m:g}m, depth="
        f"{articulation.biophilic_screen_depth_m:g}m. "
        if articulation is not None
        else ""
    )
    facade_grammar = (
        f"cladding module={','.join(f'{value:g}m' for value in panel_modules) or 'model-derived'}; "
        f"office entrance bays={len(entrance_facades)}; loading docks={loading_dock_count}. "
        f"loading door families={loading_door_families}. "
        f"{articulation_grammar}"
        "Confine office glazing and feature fins to authored entrance/design-detail bays; do not "
        "spread an office glazing ratio across plain factory elevations or shed end walls."
    )
    material_role_contract = {
        "continuous_profiled_metal_roof": palette["roof_hex"],
        "dominant_focus_wall_cladding": palette["primary_hex"],
        "plinth_structure_eaves_doors_and_docks": palette["secondary_hex"],
        "authored_glazing_only": palette["glass_hex"],
        (
            "limited_entrance_and_signage_under_"
            f"{design.design_preferences.accent_coverage_percent}_percent"
        ): palette["accent_hex"],
        "continuous_fence_and_gate": palette["boundary_hex"],
        "external_and_perimeter_site_roads": "dark charcoal asphalt, never pale concrete",
        "internal_service_yards_and_loading_aprons": palette["paving_hex"],
        "site_ground_underlay": "non-finish neutral substrate; never infer road or concrete apron",
    }
    site_boundary_contract = {
        "geometry": "authored boundary and gate openings only",
        "fence_family": design.design_preferences.boundary_kit,
        "gate_family": design.design_preferences.gate_kit,
        "construction": (
            "moderate-height industrial boundary with low concrete/masonry wall and open steel "
            "infill; vehicular gate remains full authored road width and visibly truck-capable"
        ),
        "consistency": "same height, leaf count, spacing, material and color in every view",
        "prohibited": "floating portal, disconnected frame, duplicate or relocated gate",
    }
    context_contract = {
        "mode": design.site_design.surrounding_context_mode,
        "allowed_geometry": "only context geometry visible in base RGB or semantic passes",
        "estate_topology": (
            "same gate-aligned external roads, approach connections, vegetation zones and proxy "
            "positions in every camera"
        ),
        "proxy_appearance": (
            "uniform neutral translucent massing at opacity "
            f"{design.site_design.context_opacity:g}; "
            "no facade, door, window, sign, roof equipment or opaque photoreal conversion"
        ),
        "reference_rule": (
            "context reference controls only road scale, planting realism and industrial-estate "
            "atmosphere; the camera-registered context composition guide controls proxy location "
            "and translucency; never copy or reconstruct any reference building"
        ),
        "free_pixels": "sky, atmospheric continuity and neutral ground only",
        "prohibited": (
            "invented warehouse, road, plot, fence, forest, isolated green island or copied "
            "context object"
        ),
    }
    contract: dict[str, object] = {
        "project_id": design.project_id,
        "design_revision": design.design_revision,
        "design_language": design.design_language.model_dump(),
        "material_palette": palette,
        "environment": environment,
        "presentation": design.presentation.model_dump(),
        "roof_assemblies": roof_assemblies,
        "solar_panel_building_ids": solar_panel_building_ids,
        "facade_grammar": facade_grammar,
        "material_role_contract": material_role_contract,
        "site_boundary_contract": site_boundary_contract,
        "context_contract": context_contract,
        "factory_design_system": {
            "package": design.design_preferences.design_package,
            "envelope": design.design_preferences.envelope_kit,
            "facade_rhythm": design.design_preferences.facade_rhythm_kit,
            "office_entrance": design.design_preferences.office_entrance_kit,
            "logistics": design.design_preferences.logistics_kit,
            "boundary": design.design_preferences.boundary_kit,
            "gate": design.design_preferences.gate_kit,
            "accent_coverage_percent": design.design_preferences.accent_coverage_percent,
            "loading_door_families": loading_door_families,
        },
    }
    client_prompt = design.design_preferences.client_prompt
    # A described concept keeps the look its master shows, not the neutral preset under it.
    appearance = (
        f'appearance=the client description "{client_prompt}" exactly as the approved Design '
        "Master renders it; "
        if client_prompt
        else f"style={design.design_language.style}; "
        f"materials={design.design_language.primary_material}, "
        f"{design.design_language.secondary_material}, "
        f"{design.design_language.office_material}; "
        f"palette={', '.join(str(value) for value in palette.values())}; "
    )
    material_roles = "as in the approved Design Master" if client_prompt else material_role_contract
    prompt = (
        "PROJECT DESIGN IDENTITY — immutable across all six cameras: "
        f"{appearance}"
        f"base daylight={environment['time']} {environment['weather']} (VIEW-06 may override only "
        "photography time to restrained golden/blue hour), "
        f"white balance={environment['white_balance_k']}K. "
        f"landscape={design.presentation.landscape_character}; "
        f"paving={design.presentation.paving_character}; "
        f"factory design system={contract['factory_design_system']}; "
        f"user direction={design.design_preferences.creative_prompt or 'none'}. "
        f"solar panels={solar_policy}. "
        f"facade grammar={facade_grammar} "
        f"material roles={material_roles}. "
        f"site boundary family={site_boundary_contract}. "
        f"context policy={context_contract}. "
        "All roads outside the fence and all public/perimeter approach roads remain dark asphalt; "
        "only internal service yards and loading aprons use light concrete. "
        "Use one restrained, buildable facade family, roof finish, fence/gate family, landscape "
        "vocabulary, weather, exposure and color grade throughout the view set. The Design Master "
        "controls appearance only; each current base render controls geometry and camera."
    )
    return contract, prompt


def _failed_conditioning_view_ids(render_root: Path) -> frozenset[str]:
    """Views the conditioning gate already rejected, read from its report if one exists.

    The gate runs before generation precisely so unusable cameras never reach a paid provider.
    Reading its verdict here closes the loop; an absent report means the gate has not run and
    is not treated as approval.
    """

    report_path = render_root / "conditioning_qa.json"
    if not report_path.is_file():
        return frozenset()
    try:
        document = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return frozenset()
    views = document.get("views")
    if not isinstance(views, list):
        return frozenset()
    return frozenset(
        str(item["view_id"])
        for item in views
        if isinstance(item, dict) and item.get("view_id") and item.get("status") == "fail"
    )


def _select_master_view_id(render_root: Path, cameras: tuple[Camera, ...]) -> str:
    """Choose the strongest visible design-identity view, falling back to an overview."""

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

    # For a complete view set, the overview is the only single image that carries roof, site,
    # access, boundary and context identity together. Close views can score highly from occupancy
    # while being a poor project-wide appearance anchor. The staged worker excludes this camera
    # when it independently chooses its complementary facade master.
    overall = next((camera for camera in cameras if camera.role is ViewRole.OVERALL), None)
    if overall is not None and evidence.get(overall.view_id, {}).get("status", "pass") == "pass":
        return overall.view_id

    fallback_priority = {
        ViewRole.OVERALL: 6.0,
        ViewRole.OFFICE_HERO: 5.0,
        ViewRole.HERO: 4.0,
        ViewRole.CONTEXT: 3.0,
        ViewRole.DETAIL: 2.0,
        ViewRole.LOADING_DETAIL: 1.0,
    }
    identity_bonus = {
        # Prefer a meaningful facade run with operational openings. A tight detail can report
        # high focus coverage while showing only a blank wall and cannot carry design identity.
        ViewRole.OFFICE_HERO: 18.0,
        ViewRole.HERO: 10.0,
        ViewRole.LOADING_DETAIL: 8.0,
        ViewRole.DETAIL: 2.0,
        ViewRole.CONTEXT: 3.0,
        ViewRole.OVERALL: 0.0,
    }

    def score(camera: Camera) -> tuple[float, str]:
        view_id = camera.view_id
        role = camera.role
        item = evidence.get(view_id, {})
        if not item:
            return fallback_priority.get(role, 0.0), view_id

        def numeric(name: str) -> float:
            value = item.get(name, 0.0)
            return float(value) if isinstance(value, (int, float)) else 0.0

        focus = numeric("focus_coverage")
        circulation = numeric("circulation_coverage")
        context = numeric("context_coverage")
        passed = 5.0 if item.get("status") == "pass" else -100.0
        return (
            focus * 100.0
            + circulation * 15.0
            + context * 5.0
            + identity_bonus.get(role, 0.0)
            + passed,
            view_id,
        )

    return max(cameras, key=score).view_id


def select_master_view_ids(render_root: Path, cameras: tuple[Camera, ...]) -> tuple[str, str]:
    """Select complementary site and facade masters from semantic camera evidence."""

    if not cameras:
        raise InvalidModelError("cannot select masters from an empty view set")
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

    def metric(camera: Camera, name: str) -> float:
        value = evidence.get(camera.view_id, {}).get(name, 0.0)
        return float(value) if isinstance(value, (int, float)) else 0.0

    # VIEW-01 is the primary site identity; VIEW-04 is its genuinely opposite confirmation.
    site_priority = {ViewRole.OVERALL: 100.0, ViewRole.DETAIL: 20.0}
    site_candidates = (
        tuple(camera for camera in cameras if camera.role in {ViewRole.OVERALL, ViewRole.DETAIL})
        or cameras
    )
    site = max(
        site_candidates,
        key=lambda camera: (
            site_priority.get(camera.role, 0.0)
            + metric(camera, "circulation_coverage") * 120
            + metric(camera, "context_coverage") * 90
            + metric(camera, "focus_coverage") * 20,
            camera.view_id,
        ),
    )
    facade_candidates = tuple(camera for camera in cameras if camera.view_id != site.view_id)
    facade = (
        _select_master_view_id(render_root, facade_candidates)
        if facade_candidates
        else site.view_id
    )
    return site.view_id, facade


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


def _provider_references(
    render_root: Path,
    camera: Camera,
    references: tuple[Path, ...],
    attach_context_guide: bool = True,
) -> tuple[Path, ...]:
    """Attach the camera-registered context guide before the paid provider request.

    The guide is a placement hint only where placeholder massing is meant to survive as
    positioned context. Measured against reviewed output, sending it while the prompt asks for
    generated surroundings makes the provider reproduce the translucent slabs literally: the
    image wins over the instruction. Callers that want invented context therefore withhold it.
    """

    view_root = render_root / camera.view_id
    proxy = view_root / "context_proxy_rgba.png"
    if not attach_context_guide or not proxy.is_file():
        return references
    guide = build_context_composition_guide(
        view_root / "base_rgb.png",
        proxy,
        view_root / "context_composition_guide.png",
    )
    # The Gemini balanced path has room for one appearance reference plus the spatial guide.
    # The Design Master is carried separately as style_anchor and therefore is not lost here.
    return (*references[:1], guide)


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
        reference_images_by_view: dict[str, tuple[Path, ...]] | None = None,
        quality_standard_path: Path | None = None,
        allow_failed_conditioning: bool = False,
        attach_context_guide: bool = True,
        style_pack: StylePack | None = None,
    ) -> RefinedViewSetArtifacts:
        view_set = ViewSet.model_validate_json(view_set_path.read_text(encoding="utf-8"))
        design = DesignDNA.model_validate_json(design_dna_path.read_text(encoding="utf-8"))
        render_intent_path = design_dna_path.parent / "render_intent.json"
        render_intent_sha256 = (
            hashlib.sha256(render_intent_path.read_bytes()).hexdigest()
            if render_intent_path.is_file()
            else None
        )
        if view_set.design_revision != design.design_revision:
            raise InvalidModelError("view set and Design DNA revisions do not match")
        known_view_ids = {camera.view_id for camera in view_set.cameras}
        unknown_view_ids = set(view_ids) - known_view_ids
        if unknown_view_ids:
            raise InvalidModelError(f"unknown benchmark view IDs: {sorted(unknown_view_ids)}")
        unknown_reference_view_ids = set(reference_images_by_view or {}) - known_view_ids
        if unknown_reference_view_ids:
            raise InvalidModelError(
                f"unknown per-view reference IDs: {sorted(unknown_reference_view_ids)}"
            )
        selected_cameras = tuple(
            camera for camera in view_set.cameras if not view_ids or camera.view_id in view_ids
        )
        if not selected_cameras:
            raise InvalidModelError("view-set selection cannot be empty")
        if not allow_failed_conditioning:
            rejected = _failed_conditioning_view_ids(render_root)
            blocked = sorted(
                camera.view_id for camera in selected_cameras if camera.view_id in rejected
            )
            if blocked:
                raise InvalidModelError(
                    "conditioning QA rejected these views, so generating them would spend "
                    f"provider budget on unusable cameras: {blocked}. Fix the framing and "
                    "re-render, or pass allow_failed_conditioning to override deliberately."
                )
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
        if quality_standard_path is not None and not quality_standard_path.is_file():
            raise InvalidModelError(
                f"approved facade quality standard does not exist: {quality_standard_path}"
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
                role=camera.role.value,
                context_policy=(
                    style_pack.context_policy.value if style_pack else "translucent_massing"
                ),
                design_freedom=(
                    style_pack.design_freedom.value if style_pack is not None else "photoreal_only"
                ),
                structure_guide=render_root / camera.view_id / "structure_guide.png",
                reference_images=_provider_references(
                    render_root,
                    camera,
                    (reference_images_by_view or {}).get(camera.view_id, reference_images),
                    attach_context_guide,
                ),
                aspect_ratio=camera.aspect_ratio,
                # Pro prices 1K and 2K outputs in the same tier. Keep the full-detail 2K source
                # even for preview jobs; the render profile still controls upstream GPU cost.
                image_size="2K",
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
                *(
                    hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in dict.fromkeys(
                        (
                            *reference_images,
                            *(
                                path
                                for paths in (reference_images_by_view or {}).values()
                                for path in paths
                            ),
                        )
                    )
                ),
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
        if style_pack and style_pack.design_freedom.value != "photoreal_only":
            identity_prompt = (
                "SHARED DESIGN DEVELOPMENT: one buildable architectural identity "
                "for the entire set. "
                "Preserve measured footprints, building count, height envelope, continuous roof "
                "assemblies, functional doors and site circulation. The procedural facade grammar "
                "is a starting proposal, not an immutable design. Develop the first Design Master "
                "according to the authored brief. Once approved, all later views must keep its "
                "facade family, material hierarchy, entrance treatment and restrained accent. "
                "Never copy a master's camera or relocate its architecture to fit another view.\n"
                + prompt
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

        references_by_view_id = {request.view_id: request.reference_images for request in requests}
        artifacts = tuple(
            RefineView().execute(
                renderer,
                render_root,
                result.view_id,
                output_directory,
                prompt,
                references_by_view_id[result.view_id],
                project_id=design.project_id,
                design_revision=design.design_revision,
                generated_image=result.image,
                watermark=watermark,
                design_freedom=style_pack.design_freedom.value if style_pack else "photoreal_only",
                context_policy=style_pack.context_policy.value
                if style_pack
                else "translucent_massing",
                effective_provider_model=str(
                    getattr(renderer, "provenance", {}).get("master_model")
                    or getattr(renderer, "provenance", {}).get("model")
                ),
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
            "effective_view_model": (
                getattr(renderer, "provenance", {}).get("master_model")
                or getattr(renderer, "provenance", {}).get("model")
            ),
            "master_view_id": master_view_id,
            "master_sha256": hashlib.sha256(master_image.content).hexdigest(),
            "master_provider_request_id": master_image.provider_request_id,
            "approved_master_ref": (
                str(approved_master_path) if approved_master_path is not None else None
            ),
            "facade_quality_standard_ref": (
                str(quality_standard_path) if quality_standard_path is not None else None
            ),
            "facade_quality_standard_sha256": (
                hashlib.sha256(quality_standard_path.read_bytes()).hexdigest()
                if quality_standard_path is not None
                else None
            ),
            "render_intent_ref": str(render_intent_path) if render_intent_path.is_file() else None,
            "render_intent_sha256": render_intent_sha256,
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
        generated_view_manifests: list[dict[str, object]] = []
        for camera in view_set.cameras:
            generated_manifest_path = output_directory / camera.view_id / "generation_manifest.json"
            if not generated_manifest_path.is_file():
                continue
            try:
                document = json.loads(generated_manifest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(document, dict):
                generated_view_manifests.append(document)
        reference_roles: list[str] = []
        for document in generated_view_manifests:
            input_roles = document.get("input_roles", {})
            if not isinstance(input_roles, dict):
                continue
            reference_roles.extend(
                str(role)
                for name, role in input_roles.items()
                if str(name).startswith("reference_")
            )
        reference_roles = sorted(set(reference_roles))
        manifest = {
            "schema_version": "1.0.0",
            "request_id": request_id,
            "project_id": design.project_id,
            "model_revision": model_revision,
            "design_revision": design.design_revision,
            "view_set_id": view_set.view_set_id,
            "profile": profile.value,
            "effective_design_freedom": style_pack.design_freedom.value
            if style_pack
            else "photoreal_only",
            "effective_context_policy": style_pack.context_policy.value
            if style_pack
            else "translucent_massing",
            "style_pack_snapshot": style_pack.model_dump(mode="json") if style_pack else None,
            "provider": renderer.name,
            "provider_configuration": getattr(renderer, "provenance", {}),
            "effective_view_model": (
                getattr(renderer, "provenance", {}).get("master_model")
                if profile is GenerationProfile.TENDER_FINAL
                else getattr(renderer, "provenance", {}).get("model")
            ),
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
            # Aggregate persisted per-view evidence. Dual masters intentionally use different
            # references, so the final call must not erase the Site Master's context role.
            "reference_roles": reference_roles,
            "design_identity_pack": str(identity_pack_path),
            "master_view_id": master_view_id,
            "generated_view_ids": [
                camera.view_id
                for camera in view_set.cameras
                if (output_directory / camera.view_id / "generation_manifest.json").is_file()
            ],
            "resumed_from_approved_master": approved_master_path is not None,
            "approved_master_ref": (
                str(approved_master_path) if approved_master_path is not None else None
            ),
            "facade_quality_standard_ref": (
                str(quality_standard_path) if quality_standard_path is not None else None
            ),
            "facade_quality_standard_sha256": (
                hashlib.sha256(quality_standard_path.read_bytes()).hexdigest()
                if quality_standard_path is not None
                else None
            ),
            "master_sha256": hashlib.sha256(master_image.content).hexdigest(),
            "render_intent_ref": str(render_intent_path) if render_intent_path.is_file() else None,
            "render_intent_sha256": render_intent_sha256,
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
