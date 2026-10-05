"""Tell the image model where each gate is and what it is built of, when the editor says.

Told only "gate openings ... preserve them", the model drew a generic sliding gate, or a
new one on the access road wherever it pleased. Site Forma sends the blocks it draws each
gate with (capped pillars, a barrier cabinet, a striped arm on a rest post), so this names
them. Only gates that arrive with their parts are described: a scene without them gets
exactly the prompt it always had.
"""

from __future__ import annotations

import math

from v365_archviz.application.building_brief import _described, _labels, _number, frame_side
from v365_archviz.domain.building_kind import Compass
from v365_archviz.domain.design import DesignDNA, GateDesign
from v365_archviz.domain.scene import BoundingBox, CanonicalScene, SemanticRole
from v365_archviz.domain.workflow import Camera

_ENTRANCES = {SemanticRole.MAIN_ENTRANCE: "main", SemanticRole.SECONDARY_ENTRANCE: "secondary"}


def _plot_side(plot: tuple[tuple[float, float], ...], x: float, y: float) -> Compass:
    """The compass side of the plot edge nearest to a point, by the edge's outward normal."""

    area = sum(
        plot[index][0] * plot[(index + 1) % len(plot)][1]
        - plot[(index + 1) % len(plot)][0] * plot[index][1]
        for index in range(len(plot))
    )
    best: tuple[float, Compass] | None = None
    for index, (ax, ay) in enumerate(plot):
        bx, by = plot[(index + 1) % len(plot)]
        length = math.hypot(bx - ax, by - ay)
        if length < 1e-6:
            continue
        t = max(0.0, min(1.0, ((x - ax) * (bx - ax) + (y - ay) * (by - ay)) / length**2))
        distance = math.hypot(x - (ax + t * (bx - ax)), y - (ay + t * (by - ay)))
        ux, uy = (bx - ax) / length, (by - ay) / length
        # Outward is to the right of a counter-clockwise ring, to the left of a clockwise one.
        nx, ny = (uy, -ux) if area > 0 else (-uy, ux)
        side: Compass
        if abs(nx) >= abs(ny):
            side = "east" if nx >= 0 else "west"
        else:
            side = "north" if ny >= 0 else "south"
        if best is None or distance < best[0]:
            best = (distance, side)
    assert best is not None
    return best[1]


def gate_designs(scene: CanonicalScene) -> tuple[GateDesign, ...]:
    """The gates the source draws block by block, main gates first."""

    plot = next(
        (
            element.outline
            for element in scene.elements
            if element.semantic_role is SemanticRole.SITE_BOUNDARY and element.outline
        ),
        None,
    )
    gates = []
    for element in scene.elements:
        role = _ENTRANCES.get(element.semantic_role)
        if role is None or not element.gate_parts or not element.outline:
            continue
        box = element.bounding_box
        (ax, ay), (bx, by) = element.outline[0], element.outline[1]
        top = max(part.center[2] + part.size[2] / 2 for part in element.gate_parts)
        centre_x = (box.minimum[0] + box.maximum[0]) / 2
        centre_y = (box.minimum[1] + box.maximum[1]) / 2
        gates.append(
            GateDesign(
                gate_id=element.scene_element_id,
                role=role,
                bounding_box=box,
                width_m=math.hypot(bx - ax, by - ay),
                height_m=top - box.minimum[2],
                side=_plot_side(plot, centre_x, centre_y) if plot else None,
                barrier=any(part.kind in ("arm_red", "arm_white") for part in element.gate_parts),
            )
        )
    return tuple(sorted(gates, key=lambda gate: gate.role != "main"))


def _gate_labels(gates: tuple[GateDesign, ...]) -> dict[str, str]:
    labels = {}
    for role in ("main", "secondary"):
        same = [gate for gate in gates if gate.role == role]
        for number, gate in enumerate(same, start=1):
            labels[gate.gate_id] = f"{role} gate" + (f" {number}" if len(same) > 1 else "")
    return labels


def _guard_house_near(design: DesignDNA, gate: GateDesign) -> str | None:
    """The label of a guard house within 30 m of the gate, if one stands there."""

    def centre(box: BoundingBox) -> tuple[float, float]:
        return (box.minimum[0] + box.maximum[0]) / 2, (box.minimum[1] + box.maximum[1]) / 2

    def distance(box: BoundingBox) -> float:
        (x, y), (gx, gy) = centre(box), centre(gate.bounding_box)
        return math.hypot(x - gx, y - gy)

    described = _described(design)
    near = [
        (distance(building.bounding_box), building.building_id)
        for building in described
        if building.kind == "guard_house" and building.bounding_box
    ]
    near = [item for item in near if item[0] <= 30]
    return _labels(described)[min(near)[1]] if near else None


def _description(design: DesignDNA, gate: GateDesign) -> str:
    where = f"on the {gate.side} side of the plot, " if gate.side else ""
    text = (
        f"{where}a {_number(gate.width_m)} m vehicle opening between two square light-grey "
        f"rendered pillars about {_number(gate.height_m)} m high with darker flat caps"
    )
    if gate.barrier:
        text += (
            "; a yellow-orange automatic boom-barrier cabinet stands just inside one pillar, its "
            "red-and-white striped arm lowered across the opening at about 1 m and resting on a "
            "short post by the other pillar"
        )
    if house := _guard_house_near(design, gate):
        text += f"; the {house} stands beside it"
    return text


def gate_contract(design: DesignDNA) -> str:
    """The GATES section of a concept prompt, or nothing when no gate arrives with its parts."""

    if not design.gates:
        return ""
    labels = _gate_labels(design.gates)
    lines = [
        "GATES",
        "Base RGB draws each gate where the editor placed it, in the fence line. Keep every gate "
        "at that position and opening width as the only vehicle ways through the boundary: never "
        "move, widen, add or remove one.",
        *(
            f"- The {labels[gate.gate_id]}: {_description(design, gate)}."
            for gate in design.gates
        ),
        "The opening stays clear and paved right through: no sliding or swing leaves, no arch, "
        "portal, canopy or sign gantry over it. Where this section describes a gate, it takes "
        "precedence over any general boundary or gate rule.",
    ]
    return "\n".join(lines)


def gate_view_directive(design: DesignDNA, camera: Camera) -> str:
    """Where each named gate stands in this camera's frame."""

    labels = _gate_labels(design.gates)
    placed = [
        (labels[gate.gate_id], side)
        for gate in design.gates
        if (side := frame_side(gate.bounding_box, camera))
    ]
    if not placed:
        return ""
    where = "; ".join(f"the {name} in the {side} of the frame" for name, side in placed)
    return (
        f"GATES IN THIS VIEW — {where}, at the opening width Base RGB shows and built as the "
        "GATES section describes it."
    )


def gate_set_rule(design: DesignDNA) -> str:
    """The gates line of the set identity, which every camera after the master follows."""

    if not design.gates:
        return ""
    return (
        "gates=each gate the GATES section names keeps its position, opening width, pillars and "
        "barrier in every camera; "
    )
