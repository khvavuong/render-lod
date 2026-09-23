"""The classifier against both real models, at the numbers measured from them.

`_semantic_role` and the roof clustering are pure, so the rules can be checked
with the geometry taken off the two models rather than by shipping a 40 MB .rvt
into the repository.

LOD100 is `a7d22ba36b4fa342` (model_lod100_sample_2.rvt), LOD200 is
`654f6708efd5459a` (PA-HATAY-3.rvt).
"""

from __future__ import annotations

import pytest

from v365_archviz.domain.scene import BoundingBox, SceneElement, SemanticRole, SourceElementRef
from v365_archviz.providers.ifc import (
    IDENTITY_4X4,
    _semantic_role,
    roof_clusters,
    sheds_from_roofs,
)

#: The tallest point of each measured model.
LOD200_SITE_HEIGHT = 11.5
LOD100_SITE_HEIGHT = 15.1


def role(
    entity_type: str,
    *,
    width: float,
    depth: float,
    height: float,
    base: float = 0.0,
    site: float = LOD200_SITE_HEIGHT,
    name: str | None = None,
) -> SemanticRole:
    assigned, _ = _semantic_role(
        entity_type, (width, depth, height), name, base_height=base, site_height=site
    )
    return assigned


def element(identifier: str, x0: float, x1: float, y0: float, y1: float) -> SceneElement:
    return SceneElement(
        scene_element_id=identifier,
        source=SourceElementRef(external_id=identifier, category="IfcSlab"),
        transform=IDENTITY_4X4,
        mesh_ref=f"meshes/{identifier}.npz",
        bounding_box=BoundingBox(minimum=(x0, y0, 9.0), maximum=(x1, y1, 11.5)),
        semantic_role=SemanticRole.ROOF,
        semantic_confidence=0.9,
    )


# The six roof planes of PA-HATAY-3, as measured.
LOD200_ROOFS = (
    element("r1", 48.9, 145.7, 42.6, 71.6),
    element("r2", 49.3, 146.0, 14.6, 43.6),
    element("r3", 16.4, 116.6, 111.7, 137.8),
    element("r4", 16.1, 116.4, 136.7, 162.8),
    element("r5", 144.4, 192.6, 113.1, 138.7),
    element("r6", 144.1, 192.4, 138.1, 163.7),
)


class TestLod200:
    def test_a_shed_roof_plane_is_a_roof(self) -> None:
        # IfcSlab "Basic Roof:TOLE": 96.8 x 29.0, 2.5 thick, sitting at 9.0.
        assert (
            role("IfcSlab", width=96.8, depth=29.0, height=2.5, base=9.0) is SemanticRole.ROOF
        )

    def test_an_awning_is_not_a_roof(self) -> None:
        # IfcRoof "Basic Roof:TOLE": 77.8 x 2.5, 0.4 thick, at 4.3. Trusting the
        # IFC type here would put the roof finish on the awnings and leave
        # 13,328 m2 of metal roof untouched.
        assert (
            role("IfcRoof", width=77.8, depth=2.5, height=0.4, base=4.3) is SemanticRole.CANOPY
        )

    def test_cladding_is_skin_and_never_a_building(self) -> None:
        # Basic Wall:TOLE-50, 7.8 to 10.2 tall. Under the old rules its box fell
        # in 20..500 m2 and it became a utility block: twelve imaginary service
        # buildings standing on the site.
        assert (
            role("IfcWallStandardCase", width=96.2, depth=1.2, height=10.2, base=1.2)
            is SemanticRole.ENVELOPE_PANEL
        )

    def test_the_brick_plinth_is_skin_too(self) -> None:
        # Basic Wall:BRICK-20X200X20 at z 0.0..1.2 runs the shed perimeter.
        assert (
            role("IfcWall", width=96.2, depth=1.3, height=1.2)
            is SemanticRole.ENVELOPE_PANEL
        )

    def test_a_rolling_door_is_a_dock_and_not_a_yard(self) -> None:
        # DO-STE-ROL, 3500 by 4000. The capability gate reported no logistics
        # while eighteen of these were authored, so a dock is evidence. But it
        # is not a piece of ground: called a loading zone, the camera planner
        # aimed the loading view at a three-metre door and filled the frame
        # with it — focus coverage 0.0, circulation 1.0.
        assert role("IfcDoor", width=3.5, depth=0.8, height=4.0) is SemanticRole.LOADING_DOCK

    def test_an_ordinary_door_is_not(self) -> None:
        # DO-STE-01W, 2200 by 1100.
        assert role("IfcDoor", width=1.1, depth=0.2, height=2.2) is SemanticRole.UNKNOWN

    def test_a_window_is_not_a_building(self) -> None:
        assert role("IfcWindow", width=0.8, depth=0.1, height=2.0) is SemanticRole.UNKNOWN

    def test_a_high_window_is_not_an_awning(self) -> None:
        # Sixty windows sat high enough in the shed wall to be thin and off the
        # ground, and the shape test claimed them as awnings before anything
        # asked what they were. Kind is answered first now.
        assert (
            role("IfcWindow", width=0.8, depth=0.1, height=2.0, base=7.0)
            is SemanticRole.UNKNOWN
        )


class TestLod100StaysAsItWas:
    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("Floor:SITEOPT - Cay xanh:1679299", SemanticRole.LANDSCAPE_ZONE),
            ("Floor:Duong noi bo:1", SemanticRole.SITE_ROAD),
            ("Floor:Bai xe:1", SemanticRole.PARKING),
            ("Wall:Hang rao:1", SemanticRole.SITE_BOUNDARY),
        ],
    )
    def test_named_site_elements_are_unchanged(self, name: str, expected: SemanticRole) -> None:
        # Site slabs lie at z -0.1..0.0, so the new elevated-plane branch never
        # sees them however large they are; the largest measured is 1578 m2.
        assert (
            role(
                "IfcSlab",
                width=60.0,
                depth=26.0,
                height=0.1,
                base=-0.1,
                site=LOD100_SITE_HEIGHT,
                name=name,
            )
            is expected
        )

    def test_the_massed_shed_is_still_a_shed(self) -> None:
        # 7500 m2 and 15.1 thick. Thickness is what keeps a solid mass out of
        # the roof-plane branch.
        assert (
            role(
                "IfcBuildingElementProxy",
                width=100.0,
                depth=75.0,
                height=15.1,
                site=LOD100_SITE_HEIGHT,
            )
            is SemanticRole.MAIN_SHED
        )

    def test_the_office_mass_is_still_an_office(self) -> None:
        assert (
            role(
                "IfcBuildingElementProxy",
                width=18.0,
                depth=15.0,
                height=9.0,
                site=LOD100_SITE_HEIGHT,
                name="GM-Van phong-HCN_VB:L18mxW15mxH9m 2 tang:1",
            )
            is SemanticRole.OFFICE_BLOCK
        )

    def test_an_unnamed_site_apron_is_still_a_yard(self) -> None:
        assert (
            role("IfcSlab", width=60.0, depth=26.0, height=0.1, base=-0.1, site=LOD100_SITE_HEIGHT)
            is SemanticRole.SERVICE_YARD
        )


class TestBuildingsFromRoofs:
    def test_six_planes_cover_three_buildings(self) -> None:
        clusters = roof_clusters(list(LOD200_ROOFS))
        assert len(clusters) == 3
        assert sorted(len(cluster) for cluster in clusters) == [2, 2, 2]

    def test_each_building_becomes_one_shed(self) -> None:
        sheds = sheds_from_roofs(list(LOD200_ROOFS), ground=0.0)
        assert [shed.semantic_role for shed in sheds] == [SemanticRole.MAIN_SHED] * 3
        # From the ground to the top of the roof, which is the shape the design
        # and camera planners were written to read.
        assert all(shed.bounding_box.minimum[2] == 0.0 for shed in sheds)
        assert all(shed.bounding_box.maximum[2] == 11.5 for shed in sheds)

    def test_the_sheds_are_where_the_roofs_are(self) -> None:
        sheds = sheds_from_roofs(list(LOD200_ROOFS), ground=0.0)
        boxes = sorted(
            (round(s.bounding_box.minimum[0]), round(s.bounding_box.minimum[1])) for s in sheds
        )
        assert boxes == [(16, 112), (49, 15), (144, 113)]

    def test_a_model_with_no_roof_planes_derives_nothing(self) -> None:
        assert sheds_from_roofs([], ground=0.0) == []
