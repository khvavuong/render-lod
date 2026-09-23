"""A camera may not stand inside a building.

The planner places every ground-level camera by arithmetic on a bounding box.
That arithmetic is tuned against a single shed in an open site, where any offset
lands in open air. On PA-HATAY-3 — three sheds in two rows — the loading camera
landed 0.7 m inside a cladding panel, and the frame it rendered was one hundred
percent cladding. The conditioning gate called it an excessively cropped
subject, which was true and said nothing about the real fault.

`_free_standpoint` is the only part of the planner that checks its answer
against the geometry rather than against the shape of the model it was written
for, so these are the tests that hold for a model nobody has measured yet.
"""

from __future__ import annotations

from v365_archviz.application.plan_cameras import _free_standpoint

#: The two sheds of the measured site, as (x0, y0, z0, x1, y1, z1).
SHED_SOUTH = (48.9, 14.6, -0.1, 146.0, 71.6, 11.5)
SHED_NORTH = (16.1, 111.7, -0.1, 116.6, 162.8, 11.2)
BOTH = (SHED_SOUTH, SHED_NORTH)


def inside(box: tuple[float, float, float, float, float, float], point) -> bool:
    x0, y0, z0, x1, y1, z1 = box
    return x0 <= point[0] <= x1 and y0 <= point[1] <= y1 and z0 <= point[2] <= z1


class TestEviction:
    def test_open_air_is_left_alone(self) -> None:
        # The yard between the two sheds, where a loading camera belongs.
        assert _free_standpoint((80.0, 90.0, 1.65), BOTH, 6.0) == (80.0, 90.0, 1.65)

    def test_a_camera_in_a_wall_comes_out(self) -> None:
        # The measured failure: view-06 at (50.6, 112.4), 0.7 m inside the
        # northern shed's southern wall.
        placed = _free_standpoint((50.6, 112.4, 1.65), BOTH, 6.0)
        assert not any(inside(box, placed) for box in BOTH)

    def test_it_leaves_through_the_nearest_wall(self) -> None:
        # Standing just inside the south wall, the way out is south. Pushing it
        # through the far wall instead would cross 50 m of building and put the
        # camera on the wrong side of the site, framing something else entirely.
        placed = _free_standpoint((50.6, 112.4, 1.65), BOTH, 6.0)
        assert placed[1] < SHED_NORTH[1]
        assert placed[0] == 50.6

    def test_a_camera_standing_in_front_of_a_wall_is_left_alone(self) -> None:
        # Two metres off the facade is a close elevation, which is a photograph
        # the shot solvers chose deliberately. Treating the clearance as a
        # stand-off imposed on every camera would quietly overrule them.
        placed = _free_standpoint((80.0, 73.6, 1.65), BOTH, 9.0)
        assert placed == (80.0, 73.6, 1.65)

    def test_the_clearance_is_kept(self) -> None:
        placed = _free_standpoint((50.6, 112.4, 1.65), BOTH, 9.0)
        assert placed[1] <= SHED_NORTH[1] - 9.0 + 1e-6

    def test_height_is_never_changed(self) -> None:
        # Lifting a camera out of a building vertically puts the lens on the roof.
        for start in ((50.6, 112.4, 1.65), (80.0, 40.0, 3.2), (80.0, 90.0, 1.65)):
            assert _free_standpoint(start, BOTH, 6.0)[2] == start[2]

    def test_an_aerial_camera_is_above_the_boxes_and_untouched(self) -> None:
        # It is inside both footprints in plan and inside neither in space.
        assert _free_standpoint((80.0, 40.0, 101.7), BOTH, 6.0) == (80.0, 40.0, 101.7)

    def test_a_yard_too_narrow_for_the_clearance_still_leaves_the_wall(self) -> None:
        # A 20 m gap asked to hold a 25 m stand-off. Insisting on the clearance
        # bounces the camera from one shed into the other until it runs out of
        # tries and stops inside one of them, which is the failure this whole
        # function exists to prevent. The stand-off is a preference; being in
        # open air is the guarantee.
        tight = ((0.0, 0.0, 0.0, 100.0, 40.0, 11.0), (0.0, 60.0, 0.0, 100.0, 100.0, 11.0))
        placed = _free_standpoint((50.0, 38.0, 1.65), tight, 25.0)
        assert not any(inside(box, placed) for box in tight)
        assert 40.0 < placed[1] < 60.0

    def test_a_scene_with_no_solids_is_returned_unchanged(self) -> None:
        assert _free_standpoint((50.6, 112.4, 1.65), (), 6.0) == (50.6, 112.4, 1.65)
