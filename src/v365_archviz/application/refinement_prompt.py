"""Build concise, stage-friendly generation instructions from immutable Design DNA."""

from __future__ import annotations

from pathlib import Path

from v365_archviz.domain.design import DesignDNA
from v365_archviz.domain.style_pack import ContextPolicy, StylePack

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

SITE-SURFACE AUTHORITY
The site-ground region is only the continuous model substrate beneath the authored site plan; it is
not a service yard and must never be expanded into a concrete apron. Preserve the exact visible
boundaries and hierarchy of dark asphalt site roads, concrete loading/service yards, parking,
sidewalks and planted landscape masks. Specific authored surface regions always override the
site-ground underlay. Do not merge, widen, reroute, recolour or invent any road, yard or planting
island. External and perimeter roads remain dark asphalt, never pale concrete.

ALLOWED CHANGES
Turn every approved proposal already visible in Base RGB into fully resolved, buildable industrial
architecture—not merely a texture transfer over CGI. Add photographic-scale construction finish
within those existing regions: corrugation and panel joints, flashings, gutters and downpipes,
recessed loading-door jambs, canopy edge thickness, bollards, drainage channels, kerbs, expansion
joints, glazing reflectance, material micro-roughness, contact shadows and restrained operational
wear. These details may add surface depth but may not create, remove or relocate an opening, facade
bay, road, building or roof assembly. Keep planting inside its visible zones and traffic routes
unobstructed. Use sparse correctly scaled vehicles and people only where they do not hide
architecture or access.

DESIGN RESOLUTION
The result must read as deliberately designed architecture, not a plain box with a colour stripe.
Resolve the already approved facade grammar into a clear hierarchy: a calm primary cladding field,
a durable recessed plinth, precise eave and corner flashings, dimensional structural bay rhythm,
and restrained accent only at the existing emphasized bays and doors. Give every existing loading
door a complete buildable ensemble of recessed jambs, head flashing, weather canopy, threshold,
bollards and ground drainage. Vary roughness and joint shadow at construction scale, not facade
colour or topology. Do not apply accents, fins, glazing or canopies indiscriminately to every bay.

PHOTOGRAPHIC DIRECTION
Natural full-frame architectural photography, physically plausible daylight, neutral white
balance, restrained highlight roll-off, subtle sensor detail and realistic ground contact. Preserve
the exact camera height and lens intent, whether it is an aerial overview or a human-scale facade
view. Corrugated metal must show fine seams, believable fasteners, flashing and shallow surface
variation rather than smooth plastic planes. Concrete aprons and dark asphalt must have distinct
aggregate, joints, drainage and restrained operational wear. Use ordinary buildable industrial
details, correctly scaled loading vehicles and sparse workers; avoid showroom cleanliness and
decorative excess. Distant terrain and industrial structures need natural atmospheric haze without
making the focus project soft. The site must read as an organized Vietnamese industrial park with
curbs, drainage, verges and low industrial skyline—not forest, rural wilderness, a sterile CAD
render or luxury architecture.

PROHIBITED
No camera or topology drift; no roof subdivision; no relocated/duplicate gate; no missing fence or
road; no invented opening; no saturated fantasy colour; no copied reference layout, facade or
palette; no text or logos. Keep one material, lighting and colour-grade identity across all six
views, except that VIEW-06 preserves those materials under its explicitly required late-afternoon
golden-hour photography."""


GEOMETRY_CONTRACT = """AUTHORITY
The current Base RGB fixes camera, project massing, roof geometry, footprint, authored roads,
yards, landscape zones, gate openings and fence runs. Preserve all of them exactly: same camera
position and framing, same silhouette, and the same number and placement of openings, docks and
bays. Facade articulation already present in Base RGB is approved design and must stay in its
authored locations as one consistent kit across every camera. Geometry is not negotiable.

Authored landscape zones stay planted. Every area the Base RGB shows as landscape must read as
living planting — grass, groundcover, shrubs or trees — across most of its area. Do not pave,
gravel, dry out or build over a landscape zone, and do not shrink one to a thin edge strip.

This authority covers the project and its site only. Flat, blank or translucent massing beyond
the site boundary is placeholder context, not authored geometry: it carries position and scale
but no appearance, and the CONTEXT section below governs what happens to it. Never preserve a
placeholder slab as a finished surface.

PROHIBITED
No camera movement, reframing, zoom or crop. No change to massing or roof topology. No relocated
or duplicated gate, no missing fence or road, no invented or removed opening. No text, logos,
watermarks or signage. Do not copy the layout, massing, facade or composition of any reference
image; references inform photographic quality only. Keep one material, lighting and colour-grade
identity across all views in the set."""

_CONTEXT_INSTRUCTION = {
    ContextPolicy.AUTHORED_ONLY: (
        "Render only what the model authored. Do not add neighbouring buildings, roads or "
        "infrastructure beyond the site boundary; leave the surroundings open and plain."
    ),
    ContextPolicy.TRANSLUCENT_MASSING: (
        "This project sits on one serviced lot inside an established industrial estate, and the "
        "photograph must read that way. Build the estate around it: sealed access roads with "
        "kerbs, line marking and street lighting, neighbouring lots with their own hardstanding, "
        "boundary fences, verges, service infrastructure and mature planting, all continuing to "
        "a hazy industrial horizon. The ground must never read as farmland, wasteland or an "
        "empty rural plot. One thing only is withheld: do not draw the neighbouring buildings "
        "themselves. Every neighbouring lot keeps its yard, apron and fence but its shed is left "
        "out, because those volumes are added afterwards as deterministic translucent massing so "
        "that the project inside its own fence is the single building that reads as designed. "
        "Any flat or translucent block visible in the conditioning images is that placeholder: "
        "do not photograph it as a real building and do not keep it."
    ),
    ContextPolicy.RESOLVE_PROXIES: (
        "Treat flat or translucent context massing in the conditioning images as a placement "
        "hint for where neighbouring built form belongs, and resolve it into believable real "
        "buildings. Never let placeholder grey slabs survive into the final image. Do not invent "
        "built form where the conditioning images show open ground."
    ),
    ContextPolicy.GENERATED_SURROUNDINGS: (
        "Resolve the empty sky and the ground beyond the site boundary into a believable "
        "surrounding estate consistent with the environment description, and resolve any flat or "
        "translucent context massing into real buildings. Never let placeholder grey slabs "
        "survive into the final image. Context must read as real and stay clearly secondary to "
        "the project."
    ),
}


def massing_contract(design: DesignDNA) -> str:
    """State the authored building count explicitly and protect authored open ground.

    A provider that is only told to "preserve massing" will still fill a large empty yard with
    extra sheds, and the screen cannot see it: the invented volumes sit far from every
    authoritative edge, so they are never scored. The count therefore has to be stated as a
    hard number, and the open ground has to be named as something to leave empty.
    """

    volumes = len(design.roof_assemblies)
    plural = "" if volumes == 1 else "s"
    return (
        "MASSING\n"
        f"The project has exactly {volumes} continuous roof{plural}, so exactly {volumes} main "
        f"building volume{plural}. Before you draw anything, count the long roof ridges in Base "
        f"RGB: there are {volumes}. The finished image must show the same {volumes} and no more. "
        "Counting is the check that matters here, because a single long shed under one "
        "continuous roof stays one volume however many bays, doors or dock canopies it carries. "
        "Do not add, remove, split, merge or duplicate a roof, do not extend one into a new wing, "
        "and do not turn one long roof into two parallel roofs. Yards, aprons, service areas, car "
        "parks and circulation shown as open paving in Base RGB are authored open ground: they "
        "stay open. Do not place buildings, sheds, canopies, awnings or roofed structures on "
        "them. If an open area looks large or empty, that is the authored design, not a gap to "
        "fill, and it is not a reason to recompose or crop the frame."
    )


def compose_style_prompt(pack: StylePack, design: DesignDNA | None = None) -> str:
    """Render one authored style pack into the aesthetic layers of the instruction."""

    sections = [
        f"TASK\n{pack.intent}",
        GEOMETRY_CONTRACT,
        f"ALLOWED CHANGES\n{pack.allowed_changes}",
        f"PHOTOGRAPHIC DIRECTION\n{pack.photography}",
    ]
    if design is not None:
        sections.insert(2, massing_contract(design))
    context = _CONTEXT_INSTRUCTION[pack.context_policy]
    if pack.context_direction:
        context = f"{context} {pack.context_direction}"
    sections.append(f"CONTEXT\n{context}")
    if pack.prohibited:
        sections.append(f"ADDITIONAL LIMITS\n{pack.prohibited}")
    return "\n\n".join(sections)


def build_refinement_prompt(
    design_dna_path: Path,
    prompt_file: Path | None = None,
    style_pack: StylePack | None = None,
) -> tuple[DesignDNA, str]:
    """Keep provider instructions short; geometry, masks and QA carry detailed constraints.

    Precedence is explicit: an authored style pack composes the aesthetic layers above the
    system-owned geometry contract, a raw prompt file replaces the whole base for benchmarking,
    and the built-in base is the fallback.
    """

    design = DesignDNA.model_validate_json(design_dna_path.read_text(encoding="utf-8"))
    if prompt_file is not None:
        base = prompt_file.read_text(encoding="utf-8")
    elif style_pack is not None:
        base = compose_style_prompt(style_pack, design)
    else:
        base = LAYERED_BASE_PROMPT
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
white/light concrete. The site-ground underlay is not a finish or circulation surface and must not
be interpreted as a service yard. Never swap, merge or extend these roles.
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
from AI authority and restored later. Shared daylight environment: {design.environment.time},
{design.environment.weather}, {design.environment.white_balance_k}K. Landscape:
{design.presentation.landscape_character}. User preference:
{preferences.creative_prompt or "none"}; this is soft and cannot override authority or palette."""
    return design, f"{base}\n\n{project_contract}"
