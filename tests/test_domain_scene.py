import pytest
from pydantic import ValidationError

from v365_archviz.domain.scene import (
    BoundingBox,
    CanonicalScene,
    CoordinateSystem,
    GeometryProviderKind,
    SceneElement,
    SceneSurface,
    SourceElementRef,
    SourceModelRef,
    SurfaceFrame,
)

IDENTITY = (
    (1.0, 0.0, 0.0, 0.0),
    (0.0, 1.0, 0.0, 0.0),
    (0.0, 0.0, 1.0, 0.0),
    (0.0, 0.0, 0.0, 1.0),
)


def _source() -> SourceModelRef:
    return SourceModelRef(
        provider=GeometryProviderKind.LOCAL_FIXTURE,
        project_id="project-1",
        model_id="model-1",
        version_id="sha256:abc",
    )


def _element() -> SceneElement:
    return SceneElement(
        scene_element_id="building-1",
        source=SourceElementRef(external_id="revit-guid-1", category="Mass"),
        transform=IDENTITY,
        mesh_ref="artifact://mesh/building-1.npz",
        bounding_box=BoundingBox(minimum=(0, 0, 0), maximum=(10, 20, 8)),
    )


def test_scene_rejects_dangling_surface_reference() -> None:
    surface = SceneSurface(
        surface_id="building-2:south",
        element_id="building-2",
        frame=SurfaceFrame(
            origin=(0, 0, 0),
            u_axis=(1, 0, 0),
            v_axis=(0, 0, 1),
            normal=(0, -1, 0),
        ),
        width_m=10,
        height_m=8,
    )

    with pytest.raises(ValidationError, match="missing elements"):
        CanonicalScene(
            source=_source(),
            coordinate_system=CoordinateSystem(source_to_world=IDENTITY),
            elements=(_element(),),
            surfaces=(surface,),
        )


def test_surface_frame_rejects_non_unit_axes() -> None:
    with pytest.raises(ValidationError, match="unit vectors"):
        SurfaceFrame(
            origin=(0, 0, 0),
            u_axis=(2, 0, 0),
            v_axis=(0, 0, 1),
            normal=(0, -1, 0),
        )

