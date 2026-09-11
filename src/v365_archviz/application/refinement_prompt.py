"""Build the project-specific generation prompt from immutable Design DNA."""

from __future__ import annotations

from pathlib import Path

from v365_archviz.application.refine_view import DEFAULT_PROMPT
from v365_archviz.domain.design import DesignDNA


def build_refinement_prompt(
    design_dna_path: Path,
    prompt_file: Path | None = None,
) -> tuple[DesignDNA, str]:
    prompt = prompt_file.read_text(encoding="utf-8") if prompt_file else DEFAULT_PROMPT
    design = DesignDNA.model_validate_json(design_dna_path.read_text(encoding="utf-8"))
    language = design.design_language
    environment = design.environment
    palette = design.material_palette
    presentation = design.presentation
    site_design = design.site_design
    preferences = design.design_preferences
    roof_types = sorted({building.roof.roof_type for building in design.buildings})
    focus_count = sum(building.treatment.value == "focus" for building in design.buildings)
    context_count = sum(building.treatment.value == "context" for building in design.buildings)
    auxiliary_count = sum(building.treatment.value == "auxiliary" for building in design.buildings)
    focus_facades = [
        facade
        for building in design.buildings
        if building.treatment.value == "focus"
        for facade in building.facades
    ]
    articulation = focus_facades[0].articulation if focus_facades else None
    articulation_prompt = (
        "- approved buildable facade grammar: three-part base/body/top composition; "
        f"plinth {articulation.plinth_height_m:g} m; top/eave band "
        f"{articulation.parapet_band_height_m:g} m; feature-frame depth "
        f"{articulation.feature_frame_depth_m:g} m; entrance canopy projection "
        f"{articulation.entrance_canopy_projection_m:g} m; vertical fins "
        f"{articulation.vertical_fin_count}; accent bay interval "
        f"{articulation.accent_bay_interval}. Apply this as consistent cladding joints, "
        "flashings, piers and authored entrance detailing without inventing openings.\n"
        if articulation is not None
        else ""
    )
    solar_policy = (
        "permitted only on buildings explicitly marked true"
        if any(building.roof.solar_panels for building in design.buildings)
        else "prohibited on every building"
    )
    prompt += (
        "\n\nApproved project Design DNA:\n"
        f"- style: {language.style}\n"
        f"- primary material: {language.primary_material}\n"
        f"- secondary material: {language.secondary_material}\n"
        f"- office material: {language.office_material}\n"
        f"- accent: {language.accent or 'none'}\n"
        "- approved color palette: "
        f"roof {palette.roof_hex}, primary {palette.primary_hex}, "
        f"secondary {palette.secondary_hex}, "
        f"glass {palette.glass_hex}, accent {palette.accent_hex}, "
        f"boundary {palette.boundary_hex}, paving {palette.paving_hex}\n"
        "- immutable material roles across all views: continuous roof="
        f"{palette.roof_hex}; dominant wall cladding={palette.primary_hex}; "
        f"plinth/structural grid/eaves/doors/docks={palette.secondary_hex}; authored glazing="
        f"{palette.glass_hex}; entrance/signage accent={palette.accent_hex} limited to under 8%; "
        f"fence/gate={palette.boundary_hex}; authored road/yard={palette.paving_hex}\n"
        f"- focus-factory semantic red must be recolored only with primary "
        f"{palette.primary_hex}, secondary {palette.secondary_hex}, or approved accent "
        f"{palette.accent_hex}; red is forbidden because it is not in this palette\n"
        f"- time/weather: {environment.time}, {environment.weather}\n"
        f"- white balance: {environment.white_balance_k} K\n"
        f"- landscape: {presentation.landscape_character}\n"
        f"- paving: {presentation.paving_character}\n"
        f"- entourage density: {presentation.entourage_density}\n"
        f"- approved roof instructions: {', '.join(roof_types)}\n"
        f"{articulation_prompt}"
        f"- continuous roof assembly count: {len(design.roof_assemblies)}; preserve each "
        "assembly as one longitudinal roof\n"
        f"- solar-panel policy: {solar_policy}\n"
        "- road, sidewalk, gate and landscape geometry: preserve exactly\n"
        f"- approved focus building count: {focus_count}\n"
        f"- approved opaque auxiliary building count: {auxiliary_count}; preserve each as a "
        "restrained support building, not focus architecture or translucent context\n"
        f"- approved context building count: {context_count}; generate exactly this count, "
        "plus only the deterministic perimeter massings explicitly present in semantic pixels; "
        "never infer additional context\n"
        f"- context buildings: {site_design.context_render_mode}, visual-prominence reference "
        f"{site_design.context_opacity:.2f}; pale frosted translucent planning massing with "
        "ground contact, no facade design and no glass-building appearance\n"
        f"- surrounding context mode: {site_design.surrounding_context_mode}; "
        f"perimeter massing count: {site_design.surrounding_context_count}\n"
        f"- surrounding landscape buffer: {site_design.surrounding_landscape_buffer}"
        f"\n- factory design package: {preferences.design_package}"
        f"\n- envelope construction kit: {preferences.envelope_kit}"
        f"\n- facade rhythm kit: {preferences.facade_rhythm_kit}"
        f"\n- office entrance kit: {preferences.office_entrance_kit}"
        f"\n- logistics kit: {preferences.logistics_kit}"
        f"\n- boundary kit: {preferences.boundary_kit}; gate kit: {preferences.gate_kit}"
        "\n- brand accent coverage: maximum "
        f"{preferences.accent_coverage_percent}% of visible facade"
        "\n- all kits are finish/detail instructions only; never add height, mass, floor plates, "
        "openings or circulation without matching authored semantic evidence"
        f"\n- additional creative direction: {preferences.creative_prompt or 'none'}; treat as a "
        "soft visual preference that cannot override geometry, access, roof or palette constraints"
    )
    return design, prompt
