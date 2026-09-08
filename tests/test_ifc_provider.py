from v365_archviz.domain.scene import BoundingBox, SemanticRole
from v365_archviz.providers.ifc import _box_surfaces, _semantic_role


def test_large_proxy_is_inferred_as_main_shed() -> None:
    role, confidence = _semantic_role("IfcBuildingElementProxy", (62.0, 41.5, 11.0))

    assert role is SemanticRole.MAIN_SHED
    assert confidence == 0.9


def test_two_storey_small_mass_is_inferred_as_office() -> None:
    role, confidence = _semantic_role(
        "IfcBuildingElementProxy", (13.5, 9.0, 11.0), "Khối văn phòng 2 tầng"
    )

    assert role is SemanticRole.OFFICE_BLOCK
    assert confidence == 0.9


def test_vietnamese_site_names_take_priority_over_dimensions() -> None:
    landscape, landscape_confidence = _semantic_role(
        "IfcBuildingElementProxy", (370.0, 189.0, 0.25), "cây xanh1:cây xanh"
    )
    road, road_confidence = _semantic_role(
        "IfcBuildingElementProxy", (391.0, 210.0, 0.25), "đường1:đường"
    )
    sidewalk, _ = _semantic_role("IfcBuildingElementProxy", (376.0, 195.0, 0.25), "Vỉa hè")

    assert landscape is SemanticRole.LANDSCAPE_ZONE
    assert road is SemanticRole.SITE_ROAD
    assert sidewalk is SemanticRole.SIDEWALK
    assert landscape_confidence == road_confidence == 0.98


def test_box_produces_four_orthonormal_facade_frames() -> None:
    surfaces = _box_surfaces(
        "ifc:building-1",
        BoundingBox(minimum=(0, 0, 0), maximum=(62, 41.5, 11)),
    )

    assert len(surfaces) == 4
    assert {surface.width_m for surface in surfaces} == {62.0, 41.5}
    assert {surface.height_m for surface in surfaces} == {11.0}
    assert all(surface.element_id == "ifc:building-1" for surface in surfaces)


def test_thin_site_slab_does_not_produce_facade_surfaces() -> None:
    surfaces = _box_surfaces(
        "ifc:site",
        BoundingBox(minimum=(0, 0, 0), maximum=(391, 210, 0.25)),
    )

    assert surfaces == ()
