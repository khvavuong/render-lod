from v365_archviz.domain.scene import BoundingBox, SemanticRole
from v365_archviz.providers.ifc import (
    _box_surfaces,
    _has_overlapping_focus_alternatives,
    _semantic_role,
)


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


def test_guardhouse_marks_an_authored_site_entrance() -> None:
    role, confidence = _semantic_role("IfcBuildingElementProxy", (4.0, 3.5, 3.5), "GM-Nhà bảo vệ")

    assert role is SemanticRole.MAIN_ENTRANCE
    assert confidence == 0.88


def test_vietnamese_access_and_loading_slabs_keep_operational_semantics() -> None:
    gate, gate_confidence = _semantic_role(
        "IfcSlab", (7.0, 12.0, 0.15), "Floor:SITEOPT - Cổng ra vào"
    )
    loading, loading_confidence = _semantic_role(
        "IfcSlab", (15.0, 7.0, 0.15), "Floor:SITEOPT - Sân xe lấy hàng"
    )

    assert gate is SemanticRole.MAIN_ENTRANCE
    assert loading is SemanticRole.LOADING_ZONE
    assert gate_confidence == loading_confidence == 0.9


def test_vietnamese_lot_boundary_is_not_misclassified_as_a_service_yard() -> None:
    role, confidence = _semantic_role(
        "IfcBuildingElementProxy", (220.0, 104.0, 0.2), "SITEOPT - Ranh giới lô đất"
    )

    assert role is SemanticRole.SITE_BOUNDARY
    assert confidence == 0.95


def test_master_site_ground_is_not_misclassified_as_a_service_yard() -> None:
    role, confidence = _semantic_role(
        "IfcSlab", (220.0, 104.178636, 0.05), "Floor:SITEOPT - Nền tổng mặt bằng"
    )

    assert role is SemanticRole.SITE_GROUND
    assert confidence == 0.98


def test_named_low_auxiliary_mass_keeps_utility_semantics() -> None:
    role, confidence = _semantic_role(
        "IfcBuildingElementProxy", (28.0, 8.0, 2.0), "GM-Phụ trợ L28x8x2"
    )

    assert role is SemanticRole.UTILITY_BLOCK
    assert confidence == 0.9
    surfaces = _box_surfaces(
        "utility-low",
        BoundingBox(minimum=(0, 0, 0), maximum=(28, 8, 2)),
        SemanticRole.UTILITY_BLOCK,
    )
    assert len(surfaces) == 4


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


def test_overlapping_focus_buildings_are_detected_as_ambiguous_options() -> None:
    from v365_archviz.domain.scene import SceneElement, SourceElementRef

    def shed(element_id: str, bounds: BoundingBox) -> SceneElement:
        return SceneElement(
            scene_element_id=element_id,
            source=SourceElementRef(external_id=element_id),
            transform=((1, 0, 0, 0), (0, 1, 0, 0), (0, 0, 1, 0), (0, 0, 0, 1)),
            mesh_ref=f"{element_id}.npz",
            bounding_box=bounds,
            semantic_role=SemanticRole.MAIN_SHED,
            semantic_confidence=0.9,
        )

    alternatives = [
        shed("a", BoundingBox(minimum=(0, 0, 0), maximum=(100, 50, 12))),
        shed("b", BoundingBox(minimum=(2, 1, 0), maximum=(98, 49, 12))),
    ]
    separate = [
        alternatives[0],
        shed("c", BoundingBox(minimum=(110, 0, 0), maximum=(210, 50, 12))),
    ]

    assert _has_overlapping_focus_alternatives(alternatives)
    assert not _has_overlapping_focus_alternatives(separate)
