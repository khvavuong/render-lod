"""Gates that arrive with their blocks are imported, fenced and named; a scene without them is
left as it was."""

import math
from pathlib import Path

import pytest
from pydantic import ValidationError

from tests.test_building_brief import _with_kinds
from tests.test_design_fidelity import _plan
from tests.test_office_brief import _camera
from v365_archviz.application.gate_brief import gate_contract, gate_set_rule, gate_view_directive
from v365_archviz.application.import_scene_upload import ImportSceneUpload, scene_upload_revision
from v365_archviz.application.refine_viewset import _identity_contract
from v365_archviz.application.refinement_prompt import compose_style_prompt
from v365_archviz.application.studio import STUDIO_STYLE_PACK
from v365_archviz.domain.design import DesignDNA
from v365_archviz.domain.scene import SemanticRole
from v365_archviz.domain.scene_upload import SceneUpload
from v365_archviz.domain.style_pack import StylePack

PLOT = [[-110, -80], [110, -80], [110, 80], [-110, 80]]


def _gate(gate_id: str, role: str, x: float, y: float, rotation: float) -> dict[str, object]:
    """A 10 m gate as the editor draws it: capped pillars, a cabinet, a two-stripe arm, a rest."""

    cos, sin = math.cos(rotation), math.sin(rotation)

    def part(kind: str, along: float, bottom: float, size: tuple[float, float, float]) -> dict:
        return {
            "kind": kind,
            "center": [x + along * cos, y + along * sin, bottom + size[2] / 2],
            "size": list(size),
            "rotation_rad": rotation,
        }

    return {
        "id": gate_id,
        "role": role,
        "center": [x, y],
        "width_m": 10,
        "depth_m": 1,
        "height_m": 3,
        "rotation_rad": rotation,
        "parts": [
            part("pillar", -4.5, 0, (1, 1, 2.8)),
            part("cap", -4.5, 2.8, (1.15, 1.15, 0.2)),
            part("pillar", 4.5, 0, (1, 1, 2.8)),
            part("cap", 4.5, 2.8, (1.15, 1.15, 0.2)),
            part("cabinet", -3.6, 0, (0.35, 0.35, 1)),
            part("arm_red", -1.6, 0.85, (4, 0.1, 0.1)),
            part("arm_white", 2.1, 0.85, (3.4, 0.1, 0.1)),
            part("rest", 3.7, 0, (0.15, 0.15, 0.9)),
        ],
    }


def _with_gates() -> dict[str, object]:
    upload = _with_kinds()
    # The main gate on the west edge beside the guard house at (-90, -50); a side gate south.
    upload["plot_boundary"] = PLOT
    upload["gates"] = [
        _gate("gate-west", "main", -110, -50, math.pi / 2),
        _gate("gate-south", "secondary", 60, -80, 0.0),
    ]
    return upload


def _design(tmp_path: Path) -> DesignDNA:
    return _plan(tmp_path, _with_gates())  # type: ignore[return-value]


def test_a_scene_without_gates_keeps_its_revision_and_its_prompt(tmp_path: Path) -> None:
    upload = _with_kinds()
    revision = scene_upload_revision(SceneUpload.model_validate(upload))
    assert scene_upload_revision(SceneUpload.model_validate({**upload, "gates": []})) == revision

    design: DesignDNA = _plan(tmp_path, upload)  # type: ignore[assignment]
    assert design.gates == ()
    assert gate_contract(design) == ""
    assert gate_set_rule(design) == ""
    assert gate_view_directive(design, _camera((-260.0, -50.0, 60.0))) == ""
    assert "GATES" not in compose_style_prompt(StylePack.load(STUDIO_STYLE_PACK), design)


def test_gates_become_entrances_with_their_blocks_and_the_plot_a_fence_line(
    tmp_path: Path,
) -> None:
    scene = ImportSceneUpload().execute(SceneUpload.model_validate(_with_gates()), tmp_path).scene
    elements = {element.scene_element_id: element for element in scene.elements}

    west = elements["gate-west"]
    assert west.semantic_role is SemanticRole.MAIN_ENTRANCE
    assert elements["gate-south"].semantic_role is SemanticRole.SECONDARY_ENTRANCE
    assert west.gate_parts is not None and len(west.gate_parts) == 8
    # The opening's outline runs along the gate, 10 m along y here, 1 m deep.
    assert west.outline is not None
    xs = [x for x, _ in west.outline]
    ys = [y for _, y in west.outline]
    assert max(ys) - min(ys) == pytest.approx(10)
    assert max(xs) - min(xs) == pytest.approx(1)

    plot = elements["plot-boundary"]
    assert plot.semantic_role is SemanticRole.SITE_BOUNDARY
    assert plot.outline is not None and len(plot.outline) == 4


def test_each_gate_is_described_where_it_stands_and_as_it_is_built(tmp_path: Path) -> None:
    contract = gate_contract(_design(tmp_path))

    assert contract.startswith("GATES\nBase RGB draws each gate where the editor placed it")
    assert (
        "- The main gate: on the west side of the plot, a 10 m vehicle opening between two square "
        "light-grey rendered pillars about 3 m high with darker flat caps; a yellow-orange "
        "automatic boom-barrier cabinet stands just inside one pillar, its red-and-white striped "
        "arm lowered across the opening at about 1 m and resting on a short post by the other "
        "pillar; the guard house stands beside it." in contract
    )
    assert "- The secondary gate: on the south side of the plot" in contract
    assert "no sliding or swing leaves" in contract


def test_the_section_follows_the_buildings_and_the_set_identity_carries_it(
    tmp_path: Path,
) -> None:
    design = _design(tmp_path)
    prompt = compose_style_prompt(StylePack.load(STUDIO_STYLE_PACK), design)

    assert (
        prompt.index("\nBUILDINGS\n") < prompt.index("\nGATES\n") < prompt.index("ALLOWED CHANGES")
    )
    assert "gates=each gate the GATES section names" in _identity_contract(design)[1]


def test_each_view_is_told_where_each_gate_stands(tmp_path: Path) -> None:
    # Seen from the south, the west gate is on the left and the south gate on the right.
    directive = gate_view_directive(_design(tmp_path), _camera((0.0, -260.0, 120.0)))

    assert directive.startswith("GATES IN THIS VIEW")
    assert "the main gate in the left of the frame" in directive
    assert "the secondary gate in the right of the frame" in directive


def test_an_unknown_gate_part_is_refused() -> None:
    upload = _with_gates()
    upload["gates"][0]["parts"][0]["kind"] = "portcullis"  # type: ignore[index]

    with pytest.raises(ValidationError):
        SceneUpload.model_validate(upload)


def test_the_plot_boundary_id_is_reserved() -> None:
    upload = _with_gates()
    upload["gates"][1]["id"] = "plot-boundary"  # type: ignore[index]

    with pytest.raises(ValidationError):
        SceneUpload.model_validate(upload)
