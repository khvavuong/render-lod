"""Tell the image model what each building is, when the editor says.

Base RGB draws every Site Forma building as a plain box. Told only "auxiliary buildings=3", the
model made a guard house, a substation and a pump house the same opaque shed. The editor knows
the kind of each box and the parts it drew on it (doors, glazing, a transformer yard, a tank
lid), so this names them. It adds sections only for buildings that carry a kind: a scene sent
without kinds gets exactly the prompt it always had. The office keeps its own section
(office_brief), which leaves its look to the concept on purpose.
"""

from __future__ import annotations

from v365_archviz.application.camera_framing import _camera_basis
from v365_archviz.domain.building_kind import BuildingFeatures
from v365_archviz.domain.design import BuildingDesign, BuildingTreatment, DesignDNA
from v365_archviz.domain.workflow import Camera

_NAMES = {
    "warehouse": "warehouse",
    "guard_house": "guard house",
    "substation": "substation",
    "vehicle_shed": "vehicle shed",
    "refuse_house": "refuse house",
    "pump_house": "pump house",
}


def _described(design: DesignDNA) -> list[BuildingDesign]:
    return [
        building
        for building in design.buildings
        if building.treatment is not BuildingTreatment.CONTEXT
        and building.bounding_box
        and building.kind in _NAMES
    ]


_RANKS = ("largest", "second-largest", "third-largest")


def _labels(buildings: list[BuildingDesign]) -> dict[str, str]:
    """What each building is called: its kind, ranked by footprint when the kind repeats."""

    def footprint(building: BuildingDesign) -> float:
        box = building.bounding_box
        assert box is not None
        return (box.maximum[0] - box.minimum[0]) * (box.maximum[1] - box.minimum[1])

    labels = {}
    for kind, name in _NAMES.items():
        same = sorted(
            (building for building in buildings if building.kind == kind),
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
    parts = building.features or BuildingFeatures()
    front = f"its {building.front} side" if building.front else "its front"
    kind = building.kind
    if kind == "warehouse":
        text = "a pre-engineered steel warehouse: profiled metal walls on a concrete plinth"
        if parts.roof == "gable":
            slope = f"{_number(parts.roof_slope_deg)}° " if parts.roof_slope_deg else ""
            text += f", a {slope}metal gable roof with its ridge along the long side"
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
        return text
    if kind == "guard_house":
        text = "a single-storey guard house"
        if parts.glazed_sides:
            text += f" glazed on {parts.glazed_sides} sides, looking out over the gate and the road"
        return text + (
            ", under a flat concrete roof slab that overhangs all round, with a plain door at "
            "the back"
        )
    if kind == "substation":
        text = (
            "an electrical substation: a closed masonry room with steel double doors and louvred "
            "vents"
        )
        if parts.transformer_yard:
            text += (
                f", and on {front}, inside the same footprint, an outdoor transformer standing in "
                "a small yard behind a steel mesh fence"
            )
        return text
    if kind == "vehicle_shed":
        if parts.open_sides:
            text = (
                "an open-sided steel shed for motorbikes and cars: slim steel columns and no "
                "walls, with vehicles parked under it"
            )
        else:
            text = "a steel vehicle shed with vehicles parked under it"
        if parts.roof == "mono_pitch":
            text += f", a single-slope metal roof rising towards {front}"
        return text
    if kind == "refuse_house":
        text = "a refuse house: low masonry walls"
        if parts.louvers:
            text += " with a louvred band above them"
        if parts.mesh_doors:
            text += f", steel mesh doors on {front} with the bins visible behind them"
        if parts.roof == "mono_pitch":
            text += ", a single-slope metal roof"
        return text
    text = (
        "a fire-water pump house: a closed flat-roofed room with steel double doors and louvred "
        "vents"
    )
    if parts.tank_lid:
        text += (
            f", and on {front}, inside the same footprint, the flush concrete lid of the "
            "underground water tank with access hatches and vent pipes"
        )
    return text


def _height(building: BuildingDesign) -> float:
    box = building.bounding_box
    assert box is not None
    return box.maximum[2] - box.minimum[2]


def building_contract(design: DesignDNA) -> str:
    """The BUILDINGS section of a concept prompt, or nothing when no building names its kind."""

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
            f"- The {name} about {_number(_height(building))} m high is {_description(building)}."
        )
    lines.append(
        "Where this section describes a building, its description takes precedence over any "
        "general rule for auxiliary buildings."
    )
    return "\n".join(lines)


def _frame_side(building: BuildingDesign, camera: Camera) -> str | None:
    """Left, centre or right of the frame, or None when the camera does not see it."""

    basis = _camera_basis(camera.position, camera.target)
    if basis is None:
        return None
    forward, right, _ = basis
    tan_horizontal = camera.sensor_width_mm / (2 * camera.focal_length_mm)
    box = building.bounding_box
    assert box is not None
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
        if (side := _frame_side(building, camera))
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

    if not _described(design):
        return ""
    return (
        "buildings=each building the BUILDINGS section names keeps the kind and design the "
        "approved Design Master gives it, in every camera; "
    )
