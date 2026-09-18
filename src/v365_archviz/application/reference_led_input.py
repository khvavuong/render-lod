"""Versioned R1 proposal specification. No legacy facade/camera authority is inherited."""

from __future__ import annotations

import json

VERSION = "reference-led-proposal-v1"
CONTEXT_REVISION = "vietnam-industrial-v1"
BRIEF = (
    "Create one publication-quality architectural photograph of a contemporary industrial park. "
    "Develop a disciplined, buildable architectural design: clearly distinguish the shed, "
    "human-scale office, entrance and logistics functions. Use the references as genuine "
    "architectural and photographic guidance, not merely texture samples. Choose facade rhythm, "
    "proportions, glazing, canopy, detailing and material combinations appropriate to the actual "
    "building. No arbitrary repeated decorative fins, no glass showroom, no fantasy forms. "
    "Integrate realistic tropical industrial landscaping and operational scale with believable "
    "metal, glass, asphalt and concrete, natural directional daylight and photographic depth. "
    "This is design development, not a certified construction document. Do not invent readable "
    "lettering, signs, logos, brands or captions; signage surfaces may stay blank. Generate ONE "
    "full-frame image, not a collage or brochure. Do not independently add buildings to the "
    "focus project merely to make the image attractive."
)
INTENTS = {
    "overall": "Explain the industrial park's complete layout, building hierarchy, service "
    "circulation and relationship to its surroundings from a compelling oblique aerial "
    "photograph. Unless a registered-camera block is supplied, choose the most informative and "
    "attractive camera for the project; no fixed azimuth, height, lens or corner is prescribed.",
    "office_hero": "Explain the office / entrance architecture and material quality in a "
    "compelling human-scale photograph. Show coherent glazing, canopy, facade depth, "
    "construction scale and restrained landscaping. This may be a partial view of the building. "
    "Unless a registered-camera block is supplied, choose the most attractive camera for this "
    "architectural purpose; no fixed azimuth, height, lens or corner is prescribed.",
}
REGIONAL_CONTEXT = (
    "Design and photograph this project as a contemporary industrial facility in Vietnam, "
    "not a transplanted North American or European warehouse estate. This is regional design "
    "guidance, not a fixed facade kit or measured source programme. Adapt reference features "
    "to the local setting; do not copy foreign vehicles, gate systems or construction details "
    "merely because they appear in a reference. Keep the architecture premium, restrained "
    "and buildable, without making every Vietnamese factory look identical. "
    "Where vehicles are visible and appropriate to the operation, favour plausible cab-over "
    "medium/heavy trucks, cab-over container tractor units, modest passenger cars or vans, "
    "and selectively placed motorcycles in designated parking. Use believable vehicle sizes "
    "and circulation, right-hand traffic and left-hand-drive vehicles. Do not default to "
    "long-nose American semis, oversized pickup fleets or prominent vehicle brands. "
    "If the entrance is visible, develop a functional industrial gate and compact security "
    "post with shaded waiting/check-in space and truck clearance; sliding steel gates or "
    "barrier arms are options, not mandatory motifs. Keep pedestrian/motorcycle access safe "
    "and distinguish it from heavy-vehicle circulation where the site supports it. "
    "Develop locally plausible steel-frame sheds, profiled metal roof/cladding, practical "
    "roof drainage, weather protection and a proportionate office facade with sun/rain "
    "shading. Match loading access to the actual project and user brief; do not assume "
    "every factory is a distribution centre with repeated raised loading docks. "
    "Use credible tropical planting, curbs, drainage and concrete/asphalt service yards, "
    "with maintained but not sterile operational realism. Do not impose decorative palms "
    "or resort landscaping everywhere. Regional details must fit the source envelopes "
    "and visible shot; do not add a gate, security building or vehicle fleet just to "
    "demonstrate locality. Explicit project requirements take precedence over these defaults."
)
REFERENCE_INSTRUCTIONS = {
    "factory_design_reference": "Learn the architectural hierarchy, coherent industrial "
    "cladding, well-proportioned office zones, canopy depth, glazing, logistics frontage, "
    "landscaping and credible photography. Material families may guide design unless the user "
    "brief states otherwise. Do not copy exact buildings, site layout or camera. Ignore "
    "brochure captions, graphics and branding. Adapt architecture and entrance details to "
    "the Vietnam regional context rather than transplanting a foreign industrial estate.",
    "construction_material_reference": "Use for real industrial construction scale, corrugated "
    "metal, office-to-shed relationships, service apron and operational vehicles. Do not copy "
    "its camera or site layout. Adapt operational vehicles, gate hardware and construction "
    "details to Vietnam; reference vehicles and dock types are not mandatory programme.",
    "context_realism_reference": "Use for restrained industrial-estate context, planting and "
    "photographic atmosphere; not the focus project's architecture or site layout. Keep the "
    "surroundings credible for an industrial facility in Vietnam, not a generic overseas site.",
}


def source_envelopes(scene: dict) -> list[dict]:
    focus = [
        item for item in scene["elements"] if item["semantic_role"] in {"main_shed", "office_block"}
    ]
    if not focus:
        raise ValueError("No classified source envelope; do not guess focus buildings")
    minimum = [min(item["bounding_box"]["minimum"][axis] for item in focus) for axis in range(3)]
    return [
        {
            "source_element_id": item["scene_element_id"],
            "role": item["semantic_role"],
            "minimum_m": [
                round(item["bounding_box"]["minimum"][i] - minimum[i], 3) for i in range(3)
            ],
            "maximum_m": [
                round(item["bounding_box"]["maximum"][i] - minimum[i], 3) for i in range(3)
            ],
        }
        for item in focus
    ]


def proposal_prompt(envelopes: list[dict], role: str, brief: str = "") -> str:
    if role not in INTENTS:
        raise ValueError("Unsupported proposal purpose")
    prompt = BRIEF + "\n\nPHOTOGRAPHIC PURPOSE\n" + INTENTS[role]
    prompt += "\n\nREGIONAL CONTEXT (" + CONTEXT_REVISION + ")\n" + REGIONAL_CONTEXT
    prompt += (
        "\n\nMEASURED SOURCE ENVELOPE\n"
        "Retain the relative positions, footprints and height envelopes of the focus source "
        "volumes below. Develop facade architecture inside these envelopes. Source elements "
        "may be parts of one continuous shed; do not invent an extra building at each seam. "
        "No facade kit, office count, dock count, colour zoning or motif is prescribed. "
        "New architectural details are proposals, not source facts.\n"
        + json.dumps(envelopes, ensure_ascii=False)
    )
    if brief.strip():
        prompt += "\n\nUSER DESIGN BRIEF (design preferences, not measured source facts)\n" + brief
    return prompt
