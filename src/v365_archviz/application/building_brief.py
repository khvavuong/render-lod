"""Tell the image model what each building is, when the editor says.

Base RGB draws every Site Forma building as a plain box. Told only "auxiliary buildings=3", the
model made a guard house, a substation and a pump house the same opaque shed. The editor knows
the kind of each box and the parts it drew on it (doors, glazing, a transformer yard, a tank
lid), so this names them, with the wall and roof materials the editor set. It adds sections only
for buildings that carry a kind or materials: a scene sent without them gets exactly the prompt
it always had. The office keeps its own section (office_brief), which leaves its look to the
concept on purpose; only the materials the editor set for it are named here.
"""

from __future__ import annotations

from v365_archviz.application.camera_framing import _camera_basis
from v365_archviz.domain.building_kind import BuildingFeatures, BuildingMaterial
from v365_archviz.domain.design import BuildingDesign, BuildingTreatment, DesignDNA
from v365_archviz.domain.scene import BoundingBox, SemanticRole
from v365_archviz.domain.workflow import Camera

_NAMES = {
    "warehouse": "warehouse",
    "guard_house": "guard house",
    "substation": "substation",
    "vehicle_shed": "vehicle shed",
    "refuse_house": "refuse house",
    "pump_house": "pump house",
}

#: The editor's wall material, as what the walls are made of.
_WALLS: dict[BuildingMaterial, str] = {
    "concrete": "smooth light-grey cast-in-place concrete",
    "precast": "precast concrete panels with crisp, regular joints",
    "steel": "profiled steel cladding",
    "brick": "fair-faced red-brown brick",
    "wood": "vertical timber boarding",
    "glass": "glazing in slim aluminium frames",
}
#: The editor's roof material, as the finish of the roof.
_ROOFS: dict[BuildingMaterial, str] = {
    "concrete": "concrete",
    "precast": "precast concrete",
    "steel": "profiled metal",
    "brick": "clay-tile",
    "wood": "timber",
    "glass": "glazed",
}


def _has_materials(building: BuildingDesign) -> bool:
    return building.wall_material is not None or building.roof_material is not None


def _name(building: BuildingDesign) -> str:
    """The kind the editor placed, else what its role makes it."""

    if building.kind in _NAMES:
        return _NAMES[building.kind]
    if building.kind == "office_block" or building.semantic_role is SemanticRole.OFFICE_BLOCK:
        return "office block"
    if building.semantic_role is SemanticRole.MAIN_SHED:
        return "main shed"
    return "auxiliary block"


def _described(design: DesignDNA) -> list[BuildingDesign]:
    """Buildings that carry a kind this section describes, or the materials the editor set.

    The office's kind alone is left to its own section; its materials are named here.
    """

    return [
        building
        for building in design.buildings
        if building.treatment is not BuildingTreatment.CONTEXT
        and building.bounding_box
        and (building.kind in _NAMES or _has_materials(building))
    ]


_RANKS = ("largest", "second-largest", "third-largest")


def _labels(buildings: list[BuildingDesign]) -> dict[str, str]:
    """What each building is called: its name, ranked by footprint when the name repeats."""

    def footprint(building: BuildingDesign) -> float:
        box = building.bounding_box
        assert box is not None
        return (box.maximum[0] - box.minimum[0]) * (box.maximum[1] - box.minimum[1])

    labels = {}
    for name in dict.fromkeys(_name(building) for building in buildings):
        same = sorted(
            (building for building in buildings if _name(building) == name),
            key=footprint,
            reverse=True,
        )
        for index, building in enumerate(same):
            if len(same) == 1:
                labels[building.building_id] = name
            elif len(same) == 2:
                labels[building.building_id] = f"{'larger' if index == 0 else 'smaller'} {name}"
            else:
                rank = (
                    "smallest"
                    if index == len(same) - 1
                    else _RANKS[index]
                    if index < len(_RANKS)
                    else f"{index + 1}th-largest"
                )
                labels[building.building_id] = f"{rank} {name}"
    return labels


def _number(value: float) -> str:
    return f"{value:.1f}".rstrip("0").rstrip(".")


def _doors(count: int) -> str:
    return f"{count} grade-level steel roller shutter door{'' if count == 1 else 's'}"


def _description(building: BuildingDesign) -> str:
    """What the building is, after its label and height: "is a ..." or "has ..."."""

    parts = building.features or BuildingFeatures()
    front = f"its {building.front} side" if building.front else "its front"
    kind = building.kind
    wall, roof = building.wall_material, building.roof_material
    walls = f"walls of {_WALLS[wall]}" if wall else None
    finish = _ROOFS[roof] if roof else None
    if kind == "warehouse":
        text = (
            f"a warehouse: {walls} on a concrete plinth"
            if walls
            else "a pre-engineered steel warehouse: profiled metal walls on a concrete plinth"
        )
        if parts.roof == "gable":
            slope = f"{_number(parts.roof_slope_deg)}° " if parts.roof_slope_deg else ""
            text += f", a {slope}{finish or 'metal'} gable roof with its ridge along the long side"
        elif finish:
            text += f", a {finish} roof"
        if parts.front_doors:
            text += f", {_doors(parts.front_doors)} on {front}"
            if parts.canopy_depth_m:
                text += f" under one slim steel canopy about {_number(parts.canopy_depth_m)} m deep"
        if parts.end_wall_doors:
            text += f", {parts.end_wall_doors} more in each end wall"
        if parts.high_windows:
            text += ", a row of small high-level windows under the eaves"
        if parts.louvers:
            text += ", large exhaust louvres high on the back wall"
        return f"is {text}"
    if kind == "guard_house":
        text = "a single-storey guard house" + (f" with {walls}," if walls else "")
        if parts.glazed_sides:
            text += f" glazed on {parts.glazed_sides} sides, looking out over the gate and the road"
        roof_text = (
            f"a flat {finish} roof that overhangs all round"
            if finish
            else "a flat concrete roof slab that overhangs all round"
        )
        return f"is {text.rstrip(',')}, under {roof_text}, with a plain door at the back"
    if kind == "substation":
        room = f"a closed room with {walls}" if walls else "a closed masonry room"
        text = f"an electrical substation: {room} with steel double doors and louvred vents"
        if finish:
            text += f", under a flat {finish} roof"
        if parts.transformer_yard:
            text += (
                f", and on {front}, inside the same footprint, an outdoor transformer standing in "
                "a small yard behind a steel mesh fence"
            )
        return f"is {text}"
    if kind == "vehicle_shed":
        if parts.open_sides:
            text = (
                "an open-sided steel shed for motorbikes and cars: slim steel columns and no "
                "walls, with vehicles parked under it"
            )
        elif walls:
            text = f"a vehicle shed with {walls}, with vehicles parked under it"
        else:
            text = "a steel vehicle shed with vehicles parked under it"
        if parts.roof == "mono_pitch":
            text += f", a single-slope {finish or 'metal'} roof rising towards {front}"
        elif finish:
            text += f", a {finish} roof"
        return f"is {text}"
    if kind == "refuse_house":
        text = f"a refuse house: low {walls}" if walls else "a refuse house: low masonry walls"
        if parts.louvers:
            text += " with a louvred band above them"
        if parts.mesh_doors:
            text += f", steel mesh doors on {front} with the bins visible behind them"
        if parts.roof == "mono_pitch":
            text += f", a single-slope {finish or 'metal'} roof"
        elif finish:
            text += f", a {finish} roof"
        return f"is {text}"
    if kind == "pump_house":
        room = (
            f"a closed room with {walls or 'masonry walls'} under a flat {finish or 'concrete'} "
            "roof"
            if walls or finish
            else "a closed flat-roofed room"
        )
        text = f"a fire-water pump house: {room} with steel double doors and louvred vents"
        if parts.tank_lid:
            text += (
                f", and on {front}, inside the same footprint, the flush concrete lid of the "
                "underground water tank with access hatches and vent pipes"
            )
        return f"is {text}"
    # A building without a described kind (a Generic Box, the office): only its materials.
    surfaces = [text for text in (walls, f"a {finish} roof" if finish else None) if text]
    return "has " + " and ".join(surfaces)


def _height(building: BuildingDesign) -> float:
    box = building.bounding_box
    assert box is not None
    return box.maximum[2] - box.minimum[2]


def building_contract(design: DesignDNA) -> str:
    """The BUILDINGS section of a concept prompt, or nothing when no building names its kind
    or its materials."""

    buildings = _described(design)
    if not buildings:
        return ""
    lines = [
        "BUILDINGS",
        "Base RGB draws every building as a plain box; this is what each box is. Each keeps "
        "exactly the footprint and height Base RGB gives it: the parts named here are drawn on "
        "and inside that box, never as extra volumes beside it.",
    ]
    labels = _labels(buildings)
    for building in buildings:
        name = labels[building.building_id]
        lines.append(
            f"- The {name} about {_number(_height(building))} m high {_description(building)}."
        )
    lines.append(
        "Where this section describes a building, its description takes precedence over any "
        "general rule for auxiliary buildings."
    )
    if any(_has_materials(building) for building in buildings):
        lines.append(
            "The wall and roof materials named here are what those buildings are built of: they "
            "take precedence over any general material, palette or concept direction, and every "
            "building keeps its own materials however its neighbours are finished."
        )
    return "\n".join(lines)


def frame_side(box: BoundingBox, camera: Camera) -> str | None:
    """Left, centre or right of the frame, or None when the camera does not see the box."""

    basis = _camera_basis(camera.position, camera.target)
    if basis is None:
        return None
    forward, right, _ = basis
    tan_horizontal = camera.sensor_width_mm / (2 * camera.focal_length_mm)
    centre = tuple((box.minimum[axis] + box.maximum[axis]) / 2 for axis in range(3))
    offset = tuple(centre[axis] - camera.position[axis] for axis in range(3))
    depth = sum(offset[axis] * forward[axis] for axis in range(3))
    x = sum(offset[axis] * right[axis] for axis in range(3)) / (max(depth, 1e-6) * tan_horizontal)
    if depth <= 0 or abs(x) > 1.05:
        return None
    return "left" if x < -1 / 3 else "right" if x > 1 / 3 else "centre"


def building_view_directive(design: DesignDNA, camera: Camera) -> str:
    """Where each named building stands in this camera's frame, so each box gets its own kind.

    Only the side of the frame, as for the office: a depth relation reads as a placement.
    """

    buildings = _described(design)
    labels = _labels(buildings)
    placed = [
        (labels[building.building_id], side)
        for building in buildings
        if building.bounding_box and (side := frame_side(building.bounding_box, camera))
    ]
    if not placed:
        return ""
    where = "; ".join(f"the {name} in the {side} of the frame" for name, side in placed)
    return (
        f"BUILDINGS IN THIS VIEW — {where}, each at the size Base RGB shows and drawn as the "
        "BUILDINGS section describes it."
    )


def building_set_rule(design: DesignDNA) -> str:
    """The buildings line of the set identity, which every camera after the master follows."""

    buildings = _described(design)
    if not buildings:
        return ""
    if any(_has_materials(building) for building in buildings):
        return (
            "buildings=each building the BUILDINGS section names keeps its kind, its design and "
            "the wall and roof materials that section gives it, in every camera; "
        )
    return (
        "buildings=each building the BUILDINGS section names keeps the kind and design the "
        "approved Design Master gives it, in every camera; "
    )
