"""What a view is of must show up in the proportion the geometry predicts.

The gate used to ask each role for a fixed share of the frame. No single share
can be right for two models: a service yard is two thousand square metres of
ground and a dock door is sixteen, so a number that suits the yard asks the door
to be photographed from six metres. It refused a correctly framed logistics view
of a model that had authored eighteen doors and no apron, and it refused a
LOD100 context view pointed straight at its gate, because a truck gate a hundred
metres away is half of one tenth of a percent of the frame and no framing can
change that.

The prediction replaces the number. It says what the camera would see with
nothing in the way; the render says what it did see; the gate reads the ratio.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from v365_archviz.application.camera_framing import (
    projected_frame_fraction,
    projected_frame_union,
)
from v365_archviz.application.validate_conditioning import (
    ValidateConditioningViewSet,
    _surface_triangles,
)

IDENTITY = [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]
#: A dock door as PA-HATAY-3 draws them: 4.4 m across, 4.0 m tall, set in a wall.
DOOR = ((47.8, 112.1, 0.0), (52.2, 112.8, 4.0))


class TestPrediction:
    def test_a_box_behind_the_lens_is_not_in_the_frame(self) -> None:
        # Every corner is behind the near plane. Clamping them to it, which is
        # what keeps a box straddling the lens from vanishing, would otherwise
        # report this one as filling the frame.
        assert projected_frame_fraction((50.0, 130.0, 1.7), (50.0, 160.0, 2.0), DOOR, 35.0) == 0.0

    def test_a_box_beside_the_frame_is_not_in_it(self) -> None:
        assert projected_frame_fraction((50.0, 85.0, 1.7), (200.0, 85.0, 1.7), DOOR, 35.0) == 0.0

    def test_halving_the_distance_roughly_quadruples_the_share(self) -> None:
        far = projected_frame_fraction((50.0, 72.5, 2.0), (50.0, 112.5, 2.0), DOOR, 35.0)
        near = projected_frame_fraction((50.0, 92.5, 2.0), (50.0, 112.5, 2.0), DOOR, 35.0)
        assert near == pytest.approx(far * 4, rel=0.05)

    def test_a_longer_lens_fills_more_of_the_frame(self) -> None:
        wide = projected_frame_fraction((50.0, 85.0, 2.0), (50.0, 112.5, 2.0), DOOR, 28.0)
        narrow = projected_frame_fraction((50.0, 85.0, 2.0), (50.0, 112.5, 2.0), DOOR, 70.0)
        assert narrow > wide

    def test_the_camera_inside_a_box_sees_nothing_else(self) -> None:
        room = ((-10.0, -10.0, -10.0), (10.0, 10.0, 10.0))
        assert projected_frame_fraction((0.0, 0.0, 0.0), (0.0, 30.0, 0.0), room, 35.0) == 1.0


class TestUnion:
    def test_the_same_volume_drawn_twice_is_counted_once(self) -> None:
        # Otherwise the prediction moves with how many slabs a modeller used for
        # one piece of planting, and the ratio a threshold reads from it moves
        # with the model rather than with the photograph.
        once = projected_frame_union((50.0, 85.0, 2.0), (50.0, 112.5, 2.0), [DOOR], 35.0)
        twice = projected_frame_union((50.0, 85.0, 2.0), (50.0, 112.5, 2.0), [DOOR, DOOR], 35.0)
        assert twice == pytest.approx(once)

    def test_two_separate_doors_predict_more_than_one(self) -> None:
        other = ((78.9, 112.1, 0.0), (83.3, 112.8, 4.0))
        one = projected_frame_union((65.0, 85.0, 2.0), (65.0, 112.5, 2.0), [DOOR], 28.0)
        both = projected_frame_union((65.0, 85.0, 2.0), (65.0, 112.5, 2.0), [DOOR, other], 28.0)
        assert both > one

    def test_nothing_predicts_nothing(self) -> None:
        assert projected_frame_union((0.0, 0.0, 2.0), (0.0, 30.0, 2.0), [], 35.0) == 0.0

    def test_a_planted_strip_round_a_site_predicts_its_strip_not_its_box(self) -> None:
        # Its box is the whole 200 x 120 m site; the planting is a 4 m band along the edge.
        camera = ((100.0, -160.0, 120.0), (100.0, 60.0, 0.0))
        strips = [
            ((0.0, 0.0), (200.0, 4.0)),
            ((0.0, 116.0), (200.0, 120.0)),
            ((0.0, 4.0), (4.0, 116.0)),
            ((196.0, 4.0), (200.0, 116.0)),
        ]
        triangles = [
            triangle
            for (x0, y0), (x1, y1) in strips
            for triangle in (
                ((x0, y0, 0.0), (x1, y0, 0.0), (x1, y1, 0.0)),
                ((x0, y0, 0.0), (x1, y1, 0.0), (x0, y1, 0.0)),
            )
        ]
        box = ((0.0, 0.0, 0.0), (200.0, 120.0, 0.0))

        as_box = projected_frame_union(*camera, [box], 35.0)
        as_strip = projected_frame_union(*camera, [], 35.0, triangles=triangles)

        assert as_box > 0.3
        assert 0.0 < as_strip < as_box / 4


def test_the_gate_reads_a_flat_surface_from_its_mesh_and_a_volume_from_its_box(
    tmp_path: Path,
) -> None:
    from v365_archviz.domain.scene import SceneElement

    np.savez(
        tmp_path / "yard.npz",
        vertices=np.array([[0, 0, 0], [10, 0, 0], [10, 2, 0]], dtype=float),
        faces=np.array([[0, 1, 2]]),
    )
    yard = SceneElement.model_validate(element("yard", ((0, 0, 0), (10, 10, 0)), "service_yard"))
    shed = SceneElement.model_validate(element("shed", ((0, 0, 0), (10, 10, 8)), "main_shed"))
    missing = SceneElement.model_validate(element("gone", ((0, 0, 0), (10, 10, 0)), "parking"))

    assert _surface_triangles(tmp_path, yard) == [((0, 0, 0), (10, 0, 0), (10, 2, 0))]
    assert _surface_triangles(tmp_path, shed) == []
    assert _surface_triangles(tmp_path, missing) == []


def element(identifier: str, box: tuple, role: str) -> dict:
    minimum, maximum = box
    return {
        "scene_element_id": identifier,
        "source": {"external_id": identifier},
        "transform": IDENTITY,
        "mesh_ref": f"{identifier}.npz",
        "bounding_box": {"minimum": list(minimum), "maximum": list(maximum)},
        "semantic_role": role,
    }


def rendered_gate(
    tmp_path: Path,
    *,
    position: list[float],
    target: list[float],
    dock_rows: int,
) -> dict:
    """Run the gate over a fabricated logistics frame and return its one view."""

    scene = {
        "source": {
            "provider": "local_fixture",
            "project_id": "project",
            "model_id": "model",
            "version_id": "version",
        },
        "coordinate_system": {"source_to_world": IDENTITY},
        "elements": [
            element("shed", ((16.1, 111.7, -0.1), (116.6, 162.8, 11.2)), "main_shed"),
            element("dock", DOOR, "loading_dock"),
        ],
    }
    view_set = {
        "view_set_id": "views",
        "design_revision": "design",
        "cameras": [
            {
                "view_id": "view-01",
                "role": "hero",
                "position": position,
                "target": target,
                "focal_length_mm": 35,
                "sensor_width_mm": 36,
                "aspect_ratio": "16:9",
            }
        ],
    }
    scene_path = tmp_path / "scene.json"
    view_set_path = tmp_path / "view_set.json"
    scene_path.write_text(json.dumps(scene), encoding="utf-8")
    view_set_path.write_text(json.dumps(view_set), encoding="utf-8")
    view_root = tmp_path / "renders" / "view-01"
    view_root.mkdir(parents=True)
    # Half the frame is shed, `dock_rows` of a hundred are door, the rest is sky.
    pixels = np.full((100, 100, 3), 255, dtype=np.uint8)
    pixels[:50, :, :] = (238, 108, 89)
    if dock_rows:
        pixels[50 : 50 + dock_rows, :, :] = (13, 89, 89)
    Image.fromarray(pixels, mode="RGB").save(view_root / "semantic.png")
    (view_root / "semantic_id_manifest.json").write_text(
        json.dumps(
            {
                "roles": [
                    {"semantic_role": "main_shed", "srgb8": [238, 108, 89]},
                    {"semantic_role": "loading_dock", "srgb8": [13, 89, 89]},
                ]
            }
        ),
        encoding="utf-8",
    )
    result = ValidateConditioningViewSet().execute(scene_path, view_set_path, tmp_path / "renders")
    return json.loads(result.report_path.read_text(encoding="utf-8"))["views"][0]


class TestTheGate:
    def test_a_camera_pointed_away_is_told_so(self, tmp_path: Path) -> None:
        view = rendered_gate(
            tmp_path, position=[50.0, 85.0, 2.0], target=[-200.0, 85.0, 2.0], dock_rows=0
        )
        assert view["predicted_role_target_coverage"] == 0.0
        assert "camera_role_target_not_in_frame" in view["findings"]

    def test_a_target_in_frame_but_hidden_is_a_different_fault(self, tmp_path: Path) -> None:
        # The geometry says the door is there; the render shows none of it. That
        # is the office block standing behind its own shed, and it is what this
        # check exists for.
        view = rendered_gate(
            tmp_path, position=[50.0, 85.0, 2.0], target=[50.0, 112.5, 2.0], dock_rows=0
        )
        assert view["predicted_role_target_coverage"] > 0.0
        assert "camera_role_target_not_visible" in view["findings"]
        assert "camera_role_target_not_in_frame" not in view["findings"]

    def test_a_small_target_that_shows_up_is_accepted(self, tmp_path: Path) -> None:
        # Four percent of the frame is what the geometry predicts from here, and
        # two percent of it survives the reveal of the wall it sits in. Under a
        # fixed share of the frame this was a rejection; it is a photograph.
        view = rendered_gate(
            tmp_path, position=[50.0, 85.0, 2.0], target=[50.0, 112.5, 2.0], dock_rows=2
        )
        assert view["role_target_coverage"] == pytest.approx(0.02)
        assert view["predicted_role_target_coverage"] == pytest.approx(0.04, abs=0.01)
        assert "camera_role_target_not_visible" not in view["findings"]
