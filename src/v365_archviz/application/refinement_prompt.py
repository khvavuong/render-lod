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
    auxiliary_count = sum(
        building.treatment.value == "auxiliary" for building in design.buildings
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
        f"primary {palette.primary_hex}, secondary {palette.secondary_hex}, "
        f"glass {palette.glass_hex}, accent {palette.accent_hex}, "
        f"paving {palette.paving_hex}\n"
        f"- focus-factory semantic red must be recolored only with primary "
        f"{palette.primary_hex}, secondary {palette.secondary_hex}, or approved accent "
        f"{palette.accent_hex}; red is forbidden because it is not in this palette\n"
        f"- time/weather: {environment.time}, {environment.weather}\n"
        f"- white balance: {environment.white_balance_k} K\n"
        f"- landscape: {presentation.landscape_character}\n"
        f"- paving: {presentation.paving_character}\n"
        f"- entourage density: {presentation.entourage_density}\n"
        f"- approved roof instructions: {', '.join(roof_types)}\n"
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
        f"\n- user style preset: {preferences.style_preset.value}"
        f"\n- user decor level: {preferences.decor_level.value}"
        f"\n- requested office storeys: {preferences.requested_office_storeys or 'model-derived'}; "
        "express only as facade rhythm inside the existing LOD100 envelope; never add height, "
        "mass or floor plates"
        f"\n- additional creative direction: {preferences.creative_prompt or 'none'}; treat as a "
        "soft visual preference that cannot override geometry, access, roof or palette constraints"
    )
    return design, prompt
