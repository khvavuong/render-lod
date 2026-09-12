"""Build concise, stage-friendly generation instructions from immutable Design DNA."""

from __future__ import annotations

from pathlib import Path

from v365_archviz.domain.design import DesignDNA

LAYERED_BASE_PROMPT = """TASK
Photorealistically refine this exact camera render into a bid-quality photograph of a buildable
Vietnamese industrial project.

AUTHORITY
The current Base RGB fixes camera, project massing, continuous roof geometry, footprint, authored
roads, yards, landscape zones, gate openings and fence runs. Preserve all of them exactly. Facade
details already present in Base RGB are approved shared-scene design proposals and must stay in the
same locations. Treat its clerestory datum, accent spacing, industrial shutter family, weather
canopies, jambs and bollards as one immutable facade kit across all cameras. Empty sky and the
explicit context-ground region may receive realistic industrial
estate continuity. Do not create neighbouring buildings: deterministic translucent context proxies
are composited after this step.

ALLOWED CHANGES
Improve only material response, small construction detail, contact shadows, glazing reflections,
vegetation realism, asphalt/concrete micro-texture, restrained operational wear and atmospheric
depth. Keep planting inside its visible zones and traffic routes unobstructed. Use sparse correctly
scaled vehicles and people only where they do not hide architecture or access.

PHOTOGRAPHIC DIRECTION
Natural full-frame architectural photography, physically plausible daylight, neutral white
balance, subtle sensor detail and realistic ground contact. The site must read as an organized
Vietnamese industrial park with curbs, drainage, verges and low industrial skyline—not forest,
rural wilderness, a sterile CAD render or luxury architecture.

PROHIBITED
No camera or topology drift; no roof subdivision; no relocated/duplicate gate; no missing fence or
road; no invented opening; no saturated fantasy colour; no copied reference layout, facade or
palette; no text or logos. Keep one material, lighting and colour-grade identity across all six
views."""


def build_refinement_prompt(
    design_dna_path: Path,
    prompt_file: Path | None = None,
) -> tuple[DesignDNA, str]:
    """Keep provider instructions short; geometry, masks and QA carry detailed constraints."""

    design = DesignDNA.model_validate_json(design_dna_path.read_text(encoding="utf-8"))
    base = prompt_file.read_text(encoding="utf-8") if prompt_file else LAYERED_BASE_PROMPT
    palette = design.material_palette
    preferences = design.design_preferences
    roofs = sorted({building.roof.roof_type for building in design.buildings})
    focus = [building for building in design.buildings if building.treatment.value == "focus"]
    auxiliary_count = sum(building.treatment.value == "auxiliary" for building in design.buildings)
    proposal_docks = sum(
        len(facade.loading_docks) for building in focus for facade in building.facades
    )
    proposal_entrances = sum(
        facade.office_entrance is not None for building in focus for facade in building.facades
    )
    context = design.industrial_context
    project_contract = f"""IDENTITY
Style: {design.design_language.style}.
Material roles: roof={palette.roof_hex}; dominant wall={palette.primary_hex}; secondary structure,
plinth, doors and flashings={palette.secondary_hex}; authored glazing={palette.glass_hex};
restrained
accent={palette.accent_hex} at no more than {preferences.accent_coverage_percent}% of facade;
fence/gate={palette.boundary_hex}; internal service yards/loading aprons={palette.paving_hex};
external approach and perimeter roads=dark charcoal asphalt. External roads must never render as
white/light concrete. Never swap these roles.
Roof: {", ".join(roofs)}; {len(design.roof_assemblies)} continuous assemblies, long-axis ridges.
Facade system: {preferences.envelope_kit}, {preferences.facade_rhythm_kit}; approved proposed
entrances={proposal_entrances}, approved proposed loading doors={proposal_docks}. Do not add more.
Boundary/gate: {preferences.boundary_kit}, {preferences.gate_kit}. Preserve every visible run and
opening. Keep the moderate-height low wall plus open steel infill, and make the unobstructed
authored vehicular opening read at its real truck-capable scale. Opaque auxiliary
buildings={auxiliary_count};
keep them secondary but real.
Context: {context.mode if context else design.site_design.surrounding_context_mode};
deterministic proxy count={len(context.proxy_buildings) if context else 0}; proxies are excluded
from AI authority and restored later. Environment: {design.environment.time},
{design.environment.weather}, {design.environment.white_balance_k}K. Landscape:
{design.presentation.landscape_character}. User preference:
{preferences.creative_prompt or "none"}; this is soft and cannot override authority or palette."""
    return design, f"{base}\n\n{project_contract}"
