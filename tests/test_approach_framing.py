"""The approach camera must stand off the building, not inside its footprint.

Measured on the 352 m reference shed: the approach target sat 25 m inside the footprint, so a
solved 35 m stand-off left the camera only 9 m from the facade plane. At 9 m with a 32 mm lens the
wall is the whole frame, and the rendered approach was a blank elevation receding to a vanishing
point. The conditioning gate passed it, because that wall is the focus building and filled 40% of
the frame — area share cannot tell a photograph of a building from a photograph of a wall.
"""

import math
from pathlib import Path

import pytest

from v365_archviz.application.plan_cameras import PlanStandardCameras

SCENES = {
    "A": ("480b5e6346f2877b", "R01-6f5e7d6bf311"),
    "B": ("a7d22ba36b4fa342", "R01-30c3e1709447"),
}


def _plan(model: str):
    scene_id, revision = SCENES[model]
    scene = Path(f".artifacts/scenes/{scene_id}/canonical_scene.json")
    design = Path(f".artifacts/scenes/{scene_id}/designs/{revision}/design_dna.json")
    if not scene.is_file() or not design.is_file():
        pytest.skip(f"reference scene {scene_id} is not present in this checkout")
    return PlanStandardCameras().execute(scene, design_dna_path=design)


def _focus_bounds(model: str) -> tuple[tuple[float, float], tuple[float, float]]:
    import json

    scene_id, _ = SCENES[model]
    scene = json.loads(
        Path(f".artifacts/scenes/{scene_id}/canonical_scene.json").read_text(encoding="utf-8")
    )
    boxes = [
        element["bounding_box"]
        for element in scene["elements"]
        if element["semantic_role"] in {"main_shed", "office_block"}
    ]
    minimum = tuple(min(box["minimum"][axis] for box in boxes) for axis in range(2))
    maximum = tuple(max(box["maximum"][axis] for box in boxes) for axis in range(2))
    return minimum, maximum  # type: ignore[return-value]


@pytest.mark.parametrize("model", sorted(SCENES))
def test_the_approach_camera_stands_outside_the_building(model: str) -> None:
    view_set = _plan(model)
    camera = next(c for c in view_set.cameras if c.view_id == "view-02")
    minimum, maximum = _focus_bounds(model)

    inside = all(minimum[axis] <= camera.position[axis] <= maximum[axis] for axis in range(2))

    assert not inside, "the approach camera is standing inside the building footprint"


@pytest.mark.parametrize("model", sorted(SCENES))
def test_the_approach_target_is_not_buried_in_the_mass(model: str) -> None:
    """A target inside the footprint makes the solved stand-off a fiction: the camera ends up
    against the nearest wall however far back the solver thought it was placing it."""

    view_set = _plan(model)
    camera = next(c for c in view_set.cameras if c.view_id == "view-02")
    minimum, maximum = _focus_bounds(model)
    margin = 1.0

    strictly_inside = all(
        minimum[axis] + margin < camera.target[axis] < maximum[axis] - margin for axis in range(2)
    )

    assert not strictly_inside, "the approach target sits inside the building footprint"


@pytest.mark.parametrize("model", sorted(SCENES))
def test_the_approach_looks_across_the_corner_rather_than_down_the_length(model: str) -> None:
    """A displacement weighted towards the long axis points the camera down the building and the
    frame fills with one receding wall. Weighted across, both facades meeting at the corner stay
    in view and the building reads as a volume."""

    view_set = _plan(model)
    camera = next(c for c in view_set.cameras if c.view_id == "view-02")
    minimum, maximum = _focus_bounds(model)
    long_axis = 0 if (maximum[0] - minimum[0]) >= (maximum[1] - minimum[1]) else 1

    view = [camera.target[axis] - camera.position[axis] for axis in range(2)]
    length = math.hypot(*view)
    along = abs(view[long_axis]) / length
    across = abs(view[1 - long_axis]) / length
    obliquity = math.degrees(math.atan2(along, across))

    # 0 deg is square on to the long facade, 90 deg is sighting straight down it.
    assert obliquity < 50.0, f"approach sights {obliquity:.0f} deg along the long facade"
