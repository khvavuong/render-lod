import pytest

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
from v365_archviz.providers.ifc import IDENTITY_4X4


@pytest.fixture
def valid_scene() -> CanonicalScene:
    source = SourceModelRef(
        provider=GeometryProviderKind.LOCAL_FIXTURE,
        project_id="project-1",
        model_id="model-1",
        version_id="version-1",
        source_sha256="a" * 64,
    )
    elements = (
        SceneElement(
            scene_element_id="shed-1",
            source=SourceElementRef(external_id="shed-source"),
            transform=IDENTITY_4X4,
            mesh_ref="meshes/shed.npz",
            bounding_box=BoundingBox(minimum=(0, 0, 0), maximum=(60, 40, 11)),
            semantic_role=SemanticRole.MAIN_SHED,
            semantic_confidence=0.9,
        ),
        SceneElement(
            scene_element_id="office-1",
            source=SourceElementRef(external_id="office-source"),
            transform=IDENTITY_4X4,
            mesh_ref="meshes/office.npz",
            bounding_box=BoundingBox(minimum=(10, -10, 0), maximum=(24, -1, 11)),
            semantic_role=SemanticRole.OFFICE_BLOCK,
            semantic_confidence=0.9,
        ),
    )
    return CanonicalScene(
        source=source,
        coordinate_system=CoordinateSystem(source_to_world=IDENTITY_4X4),
        elements=elements,
    )

