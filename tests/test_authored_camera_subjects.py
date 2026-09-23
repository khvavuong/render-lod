"""The camera planner must be able to aim at what the model itself drew.

A LOD200 brief says `logistics kit = preserve_model` and
`office entrance kit = preserve_model`, because the doors are already authored;
`plan_design` then invents no dock and no entrance, which is correct. But every
ground-level camera was derived from those invented features alone, so on the
honest setting there was nothing to aim at and all four ground views fell back
to arithmetic on the site bounding box. On the 176 m PA-HATAY-3 site that
arithmetic stood the loading camera 180 m from its subject with a 35 mm lens.

The eighteen doors were in the scene the whole time. These tests are about
reading them.
"""

from __future__ import annotations

from v365_archviz.application.plan_cameras import (
    _authored_dock_candidates,
    _authored_office_candidates,
    _position_on_facade,
)
from v365_archviz.domain.scene import (
    BoundingBox,
    CanonicalScene,
    CoordinateSystem,
    GeometryProviderKind,
    SceneElement,
    SemanticRole,
    SourceElementRef,
    SourceModelRef,
)
from v365_archviz.providers.ifc import IDENTITY_4X4, scene_surfaces

#: shed:03 of PA-HATAY-3, as measured.
SHED = BoundingBox(minimum=(48.9, 14.6, -0.1), maximum=(146.0, 71.6, 11.5))
#: The office block beside it.
OFFICE = BoundingBox(minimum=(48.8, 70.6, 0.0), maximum=(66.9, 85.8, 9.0))
#: DO-STE-ROL in the shed's north wall, and one in its west wall.
NORTH_DOOR = BoundingBox(minimum=(111.0, 70.6, 0.0), maximum=(115.4, 71.2, 4.0))
WEST_DOOR = BoundingBox(minimum=(49.3, 40.4, 0.0), maximum=(50.0, 44.8, 4.0))


def element(identifier: str, box: BoundingBox, role: SemanticRole, category: str) -> SceneElement:
    return SceneElement(
        scene_element_id=identifier,
        source=SourceElementRef(external_id=identifier, category=category),
        transform=IDENTITY_4X4,
        mesh_ref=f"meshes/{identifier}.npz",
        bounding_box=box,
        semantic_role=role,
        semantic_confidence=0.9,
    )


def scene_of(*elements: SceneElement) -> CanonicalScene:
    return CanonicalScene(
        source=SourceModelRef(
            provider=GeometryProviderKind.LOCAL_FIXTURE,
            project_id="VBT1-DU-AN-TEST-1",
            model_id="PA-HATAY-3",
            version_id="1",
        ),
        coordinate_system=CoordinateSystem(source_to_world=IDENTITY_4X4),
        elements=tuple(elements),
        surfaces=tuple(scene_surfaces(list(elements))),
    )


MEASURED = scene_of(
    element("shed:03", SHED, SemanticRole.MAIN_SHED, "DerivedMainShed"),
    element("office", OFFICE, SemanticRole.OFFICE_BLOCK, "IfcBuildingElementProxy"),
    element("dock-north", NORTH_DOOR, SemanticRole.LOADING_DOCK, "IfcDoor"),
    element("dock-west", WEST_DOOR, SemanticRole.LOADING_DOCK, "IfcDoor"),
)


class TestReadingADoorOffTheModel:
    def test_a_door_is_placed_on_the_wall_it_is_drawn_in(self) -> None:
        surface, dock = next(
            (candidate[1], candidate[2]) for candidate in _authored_dock_candidates(MEASURED)
        )
        assert surface is not None
        assert surface.surface_id == "shed:03:north"
        # 113.2 m along a wall running 146.0 back to 48.9.
        assert round(dock.u, 3) == round((146.0 - 113.2) / 97.1, 3)

    def test_the_door_keeps_its_measured_width(self) -> None:
        widths = {
            round(candidate[2].width_m, 1) for candidate in _authored_dock_candidates(MEASURED)
        }
        assert widths == {4.4}

    def test_one_elevation_is_offered_and_not_scattered_doors(self) -> None:
        # Two walls hold a door each. A logistics view is of an elevation, so
        # only one of them may be offered: aiming at the other door puts the
        # camera at the quiet end of the building with nothing else to show.
        surfaces = {candidate[1].surface_id for candidate in _authored_dock_candidates(MEASURED)}
        assert len(surfaces) == 1

    def test_the_wall_with_the_most_doors_wins(self) -> None:
        # The operational face is the one the model fills with doors, however
        # wide the quiet walls are.
        busy = scene_of(
            element("shed:03", SHED, SemanticRole.MAIN_SHED, "DerivedMainShed"),
            element("dock-north", NORTH_DOOR, SemanticRole.LOADING_DOCK, "IfcDoor"),
            element("dock-west-1", WEST_DOOR, SemanticRole.LOADING_DOCK, "IfcDoor"),
            element(
                "dock-west-2",
                BoundingBox(minimum=(49.3, 50.4, 0.0), maximum=(50.0, 54.8, 4.0)),
                SemanticRole.LOADING_DOCK,
                "IfcDoor",
            ),
        )
        candidates = _authored_dock_candidates(busy)
        assert {candidate[1].surface_id for candidate in candidates} == {"shed:03:west"}
        # Both west doors, each from both approach sides.
        assert len(candidates) == 4

    def test_the_candidates_are_marked_as_the_model_s_own(self) -> None:
        assert all(
            candidate[2].evidence_state.value == "authored"
            for candidate in _authored_dock_candidates(MEASURED)
        )

    def test_a_model_with_no_docks_offers_none(self) -> None:
        bare = scene_of(element("shed:03", SHED, SemanticRole.MAIN_SHED, "DerivedMainShed"))
        assert _authored_dock_candidates(bare) == []

    def test_a_door_nowhere_near_a_wall_is_ignored(self) -> None:
        # A door standing free in the yard belongs to no elevation, and guessing
        # one would aim the logistics camera at a wall that has no door in it.
        stray = scene_of(
            element("shed:03", SHED, SemanticRole.MAIN_SHED, "DerivedMainShed"),
            element(
                "stray",
                BoundingBox(minimum=(90.0, 95.0, 0.0), maximum=(94.4, 95.6, 4.0)),
                SemanticRole.LOADING_DOCK,
                "IfcDoor",
            ),
        )
        assert _authored_dock_candidates(stray) == []


class TestPositionOnFacade:
    def test_a_point_past_the_end_of_a_wall_is_not_on_it(self) -> None:
        north = next(s for s in MEASURED.surfaces if s.surface_id == "shed:03:north")
        assert _position_on_facade(north, (200.0, 71.0)) is None

    def test_a_point_deep_inside_the_building_is_not_on_its_far_wall(self) -> None:
        north = next(s for s in MEASURED.surfaces if s.surface_id == "shed:03:north")
        assert _position_on_facade(north, (100.0, 40.0)) is None


class TestReadingTheOfficeOffTheModel:
    def test_the_office_offers_its_widest_elevation(self) -> None:
        candidates = _authored_office_candidates(MEASURED)
        assert len(candidates) == 1
        _facade, surface, entrance = candidates[0]
        assert surface is not None and entrance is not None
        assert surface.element_id == "office"
        assert round(surface.width_m, 1) == 18.1
        assert entrance.u == 0.5

    def test_a_model_with_no_office_offers_none(self) -> None:
        bare = scene_of(element("shed:03", SHED, SemanticRole.MAIN_SHED, "DerivedMainShed"))
        assert _authored_office_candidates(bare) == []
