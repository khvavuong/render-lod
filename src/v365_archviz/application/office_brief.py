"""Tell the image model which building is the office and how it relates to the rest.

The office is the face of an industrial project, and in a base render it is just another box in
the shed's cladding: left unnamed, it came back as a second warehouse. Naming it is not enough
either, because a prescribed office look (curtain wall, fins, canopy) is one style imposed on
every concept. So this states only role, hierarchy and coherence; the expression comes from the
concept's own style direction.
"""

from __future__ import annotations

from v365_archviz.application.camera_framing import _camera_basis
from v365_archviz.domain.design import BuildingDesign, BuildingTreatment, DesignDNA
from v365_archviz.domain.scene import SemanticRole
from v365_archviz.domain.workflow import Camera

_RANKS = ("largest", "second-largest", "third-largest")


def _project_buildings(design: DesignDNA) -> list[BuildingDesign]:
    return [
        building
        for building in design.buildings
        if building.treatment is not BuildingTreatment.CONTEXT and building.bounding_box
    ]


def _offices(design: DesignDNA) -> list[BuildingDesign]:
    return [
        building
        for building in _project_buildings(design)
        if building.semantic_role is SemanticRole.OFFICE_BLOCK
    ]


def _footprint(building: BuildingDesign) -> float:
    box = building.bounding_box
    assert box is not None
    return (box.maximum[0] - box.minimum[0]) * (box.maximum[1] - box.minimum[1])


def _describe(building: BuildingDesign, ranked: list[BuildingDesign]) -> str:
    box = building.bounding_box
    assert box is not None
    # Footprint sides are left out: a rotated block's bounding box overstates them.
    storeys = f"{building.storeys}-storey " if building.storeys else ""
    text = f"the {storeys}block about {box.maximum[2] - box.minimum[2]:.0f} m high"
    if len(ranked) > 1:
        index = ranked.index(building)
        rank = (
            "smallest"
            if index == len(ranked) - 1
            else _RANKS[index]
            if index < len(_RANKS)
            else f"{index + 1}th-largest"
        )
        text += f", the {rank} of the {len(ranked)} buildings"
    return text


def office_contract(design: DesignDNA) -> str:
    """The OFFICE section of a concept prompt, or nothing when the model has no office."""

    offices = _offices(design)
    if not offices:
        return ""
    ranked = sorted(_project_buildings(design), key=_footprint, reverse=True)
    named = "; ".join(_describe(office, ranked) for office in offices)
    subject = "The office is" if len(offices) == 1 else f"The {len(offices)} offices are"
    lines = [
        "OFFICE",
        f"{subject} {named}. Within its fixed envelope it carries the most design intent of the "
        "project: its facade composition, materials, shading and detail are resolved further "
        "than on any other building. Its expression is not prescribed: derive it from this "
        "concept's own style direction, as the architect developing this scheme would.",
    ]
    if len(offices) < len(ranked):
        lines.append(
            "Office and the other buildings are one project by one architect: they share the "
            "palette and the family of materials, at least one design idea legible on both, "
            "and aligned horizontal lines where they meet. The other buildings stay calmer and "
            "more disciplined; the office is the most resolved expression of the same language, "
            "never a different style."
        )
    storeys = {office.storeys for office in offices if office.storeys}
    floors = f" Its facade reads as {storeys.pop()} floor levels." if len(storeys) == 1 else ""
    lines.append(
        "Its footprint and height stay exactly as Base RGB shows, with nothing added on top or "
        f"beside it.{floors} Everything you design must be buildable and suit the tropical "
        "climate."
    )
    # Told how the office is entered and meets the ground, or that it is the project's face,
    # the model lowered the camera to show its entrance.
    lines.append(
        "This is a design brief, not a camera brief: the office keeps exactly the place and "
        "size in the frame that Base RGB gives it, and the camera does not move."
    )
    return "\n".join(lines)


def office_view_directive(design: DesignDNA, camera: Camera) -> str:
    """Where the office stands in this camera's frame, so the right box gets the design."""

    offices = _offices(design)
    if not offices:
        return ""
    basis = _camera_basis(camera.position, camera.target)
    if basis is None:
        return ""
    forward, right, _ = basis
    tan_horizontal = camera.sensor_width_mm / (2 * camera.focal_length_mm)

    # Only the side of the frame. "In front of the largest building", true in depth, was read
    # as a placement, and the model moved the office there and recomposed the whole picture.
    phrases = []
    for office in offices:
        box = office.bounding_box
        assert box is not None
        centre = tuple((box.minimum[axis] + box.maximum[axis]) / 2 for axis in range(3))
        offset = tuple(centre[axis] - camera.position[axis] for axis in range(3))
        depth = sum(offset[axis] * forward[axis] for axis in range(3))
        x = sum(offset[axis] * right[axis] for axis in range(3)) / (
            max(depth, 1e-6) * tan_horizontal
        )
        if depth <= 0 or abs(x) > 1.05:
            phrases.append("outside this frame")
            continue
        side = "left" if x < -1 / 3 else "right" if x > 1 / 3 else "centre"
        phrases.append(f"in the {side} of the frame")
    if all(phrase == "outside this frame" for phrase in phrases):
        return (
            "OFFICE IN THIS VIEW — the office is outside this frame; do not give any other "
            "building its design."
        )
    return (
        f"OFFICE IN THIS VIEW — the office stands {'; '.join(phrases)}, at the size Base RGB "
        "shows. It carries the office design in full; no other building takes it."
    )


def office_set_rule(design: DesignDNA) -> str:
    """The office line of the set identity, which every camera after the master follows."""

    if not _offices(design):
        return ""
    return (
        "office=the office keeps exactly the design the approved Design Master gives it, in "
        "every camera, as the most resolved building of the set in the same language as the "
        "others; "
    )
