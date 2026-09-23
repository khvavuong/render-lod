"""IFC to Canonical Scene provider using IfcOpenShell tessellation."""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import ifcopenshell
import ifcopenshell.geom
import numpy as np

from v365_archviz.artifacts import atomic_write
from v365_archviz.domain.scene import (
    BoundingBox,
    CanonicalScene,
    CoordinateSystem,
    SceneElement,
    SceneSurface,
    SemanticRole,
    SourceElementRef,
    SurfaceFrame,
)
from v365_archviz.errors import InvalidModelError
from v365_archviz.providers.contracts import GeometryExtractionRequest

IDENTITY_4X4 = (
    (1.0, 0.0, 0.0, 0.0),
    (0.0, 1.0, 0.0, 0.0),
    (0.0, 0.0, 1.0, 0.0),
    (0.0, 0.0, 0.0, 1.0),
)


@dataclass(frozen=True, slots=True)
class IfcDiagnostic:
    entity_id: int
    entity_type: str
    global_id: str | None
    status: str
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class _Measured:
    """One tessellated element, before anything has been decided about it."""

    scene_element_id: str
    global_id: str
    ifc_type: str
    name: str | None
    mesh_ref: str
    bounding_box: BoundingBox
    dimensions: tuple[float, float, float]


def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", value)


#: A roof plane is thin. The LOD100 shed is a solid mass 15.1m thick and must
#: stay out of this branch; the LOD200 roof slabs are 2.2 to 2.5m.
ROOF_MAX_THICKNESS_M = 3.0
#: And it is high up, as a fraction of the building rather than an absolute, so
#: a lower shed is still found. Measured: LOD200 roof at 9.0 of 11.5 (0.78),
#: canopies at 4.3 (0.37).
ROOF_MIN_HEIGHT_FRACTION = 0.6
ROOF_MIN_HEIGHT_M = 3.0
#: And it covers a building. Measured: shed roofs 1233 to 2813 m², canopies
#: 66 to 192 m². Site slabs reach 1578 m² but lie at z ≈ 0, so the height test is
#: what keeps them out, not this one.
ROOF_MIN_AREA_M2 = 500.0
#: A canopy is a strip. Measured: 2.0 to 2.5m wide, 33 to 78m long.
CANOPY_MAX_WIDTH_M = 4.0
#: A door this wide is a dock door. Measured: DO-STE-ROL is 3500 by 4000, the
#: ordinary DO-STE-01W is 2200 by 1100.
DOCK_DOOR_MIN_WIDTH_M = 3.0


def _semantic_role(
    entity_type: str,
    dimensions: tuple[float, float, float],
    name: str | None = None,
    *,
    base_height: float = 0.0,
    site_height: float = 0.0,
) -> tuple[SemanticRole, float]:
    width, depth, height = dimensions
    footprint_area = width * depth
    normalized_name = "".join(
        character
        for character in unicodedata.normalize("NFD", (name or "").casefold())
        if unicodedata.category(character) != "Mn"
    ).replace("đ", "d")
    # A master site-ground slab is an underlay for the authored roads, loading yards,
    # parking and landscape islands above it. Treating it as a service yard tells the
    # image model that the entire property is one concrete apron and destroys the site
    # plan in aerial views.
    if any(
        token in normalized_name
        for token in ("nen tong mat bang", "site ground", "site base", "ground plane")
    ):
        return SemanticRole.SITE_GROUND, 0.98
    if any(token in normalized_name for token in ("cay xanh", "landscape", "green")):
        return SemanticRole.LANDSCAPE_ZONE, 0.98
    if any(token in normalized_name for token in ("via he", "sidewalk", "pavement")):
        return SemanticRole.SIDEWALK, 0.98
    if any(token in normalized_name for token in ("duong", "road", "driveway")):
        return SemanticRole.SITE_ROAD, 0.98
    if any(
        token in normalized_name
        for token in (
            "cong chinh",
            "cong vao",
            "cong ra vao",
            "loi ra vao",
            "main gate",
            "entry gate",
            "site entrance",
        )
    ):
        return SemanticRole.MAIN_ENTRANCE, 0.9
    if any(token in normalized_name for token in ("nha bao ve", "guardhouse", "security house")):
        # LOD100 masterplans commonly encode the controlled entrance as its
        # guardhouse mass instead of a separately modelled gate leaf.
        return SemanticRole.MAIN_ENTRANCE, 0.88
    if any(
        token in normalized_name
        for token in (
            "hang rao",
            "ranh gioi",
            "ranh dat",
            "fence",
            "boundary",
            "property line",
        )
    ):
        return SemanticRole.SITE_BOUNDARY, 0.95
    if any(token in normalized_name for token in ("bai xe", "parking")):
        return SemanticRole.PARKING, 0.9
    if any(token in normalized_name for token in ("san xe lay hang", "loading yard", "loading")):
        return SemanticRole.LOADING_ZONE, 0.9
    if any(
        token in normalized_name
        for token in (
            "phu tro",
            "tram xu ly",
            "xu ly nuoc thai",
            "utility",
            "service building",
        )
    ):
        return SemanticRole.UTILITY_BLOCK, 0.9
    if height <= 0.5 and footprint_area >= 500:
        return SemanticRole.SERVICE_YARD, 0.75
    # A LOD200 model draws the building rather than massing it, so the rules
    # below read what an element is. Kind before shape: a window set high in a
    # wall is also thin and off the ground, and sixty of them were read as
    # awnings until the openings were answered before the roof test.
    if entity_type.startswith("IfcWall"):
        return SemanticRole.ENVELOPE_PANEL, 0.85
    if entity_type == "IfcDoor" and max(width, depth) >= DOCK_DOOR_MIN_WIDTH_M:
        return SemanticRole.LOADING_ZONE, 0.8
    if entity_type in {"IfcDoor", "IfcWindow"}:
        return SemanticRole.UNKNOWN, 0.4
    if height <= ROOF_MAX_THICKNESS_M and base_height >= ROOF_MIN_HEIGHT_M:
        # Thin and off the ground. Which of the two it is depends on how high it
        # sits within this building and how much it covers: the measured shed
        # roof is at 0.78 of the building over 1233 m², the awnings at 0.37 over
        # 192 m² in strips two metres wide.
        if (
            base_height >= ROOF_MIN_HEIGHT_FRACTION * site_height
            and footprint_area >= ROOF_MIN_AREA_M2
            and min(width, depth) > CANOPY_MAX_WIDTH_M
        ):
            return SemanticRole.ROOF, 0.9
        return SemanticRole.CANOPY, 0.8
    if entity_type == "IfcBuildingElementProxy" and footprint_area >= 500 and height >= 5:
        return SemanticRole.MAIN_SHED, 0.9
    if 80 <= footprint_area < 500 and height >= 8:
        confidence = 0.9 if "2 tang" in normalized_name else 0.8
        return SemanticRole.OFFICE_BLOCK, confidence
    if 20 <= footprint_area < 500 and height >= 3:
        return SemanticRole.UTILITY_BLOCK, 0.65
    return SemanticRole.UNKNOWN, 0.4


def _box_surfaces(
    element_id: str,
    bounding_box: BoundingBox,
    element_role: SemanticRole = SemanticRole.UNKNOWN,
) -> tuple[SceneSurface, ...]:
    x0, y0, z0 = bounding_box.minimum
    x1, y1, z1 = bounding_box.maximum
    width = x1 - x0
    depth = y1 - y0
    height = z1 - z0
    if width <= 0 or depth <= 0 or height <= 0:
        return ()
    if height < 3.0 and element_role is not SemanticRole.UTILITY_BLOCK:
        return ()
    # A wall, a roof plane and an awning are parts of a building's skin, not
    # masses with four sides of their own. Boxing each of them would hand the
    # design planner dozens of facades facing every direction; the shed derived
    # from the roofs is what carries this building's real faces.
    if element_role in {
        SemanticRole.ENVELOPE_PANEL,
        SemanticRole.ROOF,
        SemanticRole.CANOPY,
    }:
        return ()
    definitions = (
        ("south", (x0, y0, z0), (1.0, 0.0, 0.0), (0.0, -1.0, 0.0), width),
        ("north", (x1, y1, z0), (-1.0, 0.0, 0.0), (0.0, 1.0, 0.0), width),
        ("east", (x1, y0, z0), (0.0, 1.0, 0.0), (1.0, 0.0, 0.0), depth),
        ("west", (x0, y1, z0), (0.0, -1.0, 0.0), (-1.0, 0.0, 0.0), depth),
    )
    return tuple(
        SceneSurface(
            surface_id=f"{element_id}:{name}",
            element_id=element_id,
            frame=SurfaceFrame(
                origin=origin,
                u_axis=u_axis,
                v_axis=(0.0, 0.0, 1.0),
                normal=normal,
            ),
            width_m=surface_width,
            height_m=height,
            semantic_role=(SemanticRole.PRIMARY_FACADE if name == "south" else element_role),
        )
        for name, origin, u_axis, normal, surface_width in definitions
    )


def _footprints_touch(first: BoundingBox, second: BoundingBox, tolerance: float = 1.5) -> bool:
    """Whether two footprints overlap or sit against each other in plan."""

    ax0, ay0, _ = first.minimum
    ax1, ay1, _ = first.maximum
    bx0, by0, _ = second.minimum
    bx1, by1, _ = second.maximum
    return (
        ax0 - tolerance <= bx1 and bx0 - tolerance <= ax1
        and ay0 - tolerance <= by1 and by0 - tolerance <= ay1
    )


def roof_clusters(roofs: list[SceneElement]) -> list[list[SceneElement]]:
    """Group roof planes into the buildings they cover.

    A shed is usually roofed by several spans laid side by side — the measured
    model has six planes over three buildings, each pair sharing about a metre
    of edge. Grouping by adjacency recovers the buildings without needing a
    name, a material or an `IfcSpace`, none of which separated them.
    """

    remaining = list(roofs)
    clusters: list[list[SceneElement]] = []
    while remaining:
        cluster = [remaining.pop()]
        grew = True
        while grew:
            grew = False
            for candidate in list(remaining):
                if any(_footprints_touch(candidate.bounding_box, m.bounding_box) for m in cluster):
                    cluster.append(candidate)
                    remaining.remove(candidate)
                    grew = True
        clusters.append(cluster)
    return clusters


def _shed_from_cluster(cluster: list[SceneElement], index: int, ground: float) -> SceneElement:
    """One building, as the mass the design and camera planners expect.

    They were written against LOD100, where a shed arrives as a single solid.
    Rather than teach eleven call sites about roof planes, the planes are
    resolved into the same shape those call sites already read.
    """

    x0 = min(item.bounding_box.minimum[0] for item in cluster)
    y0 = min(item.bounding_box.minimum[1] for item in cluster)
    x1 = max(item.bounding_box.maximum[0] for item in cluster)
    y1 = max(item.bounding_box.maximum[1] for item in cluster)
    top = max(item.bounding_box.maximum[2] for item in cluster)
    return SceneElement(
        scene_element_id=f"shed:{index:02d}",
        source=SourceElementRef(
            external_id=f"shed-{index:02d}",
            category="DerivedMainShed",
            type_name=f"mái gộp từ {len(cluster)} tấm",
        ),
        transform=IDENTITY_4X4,
        mesh_ref=cluster[0].mesh_ref,
        bounding_box=BoundingBox(minimum=(x0, y0, ground), maximum=(x1, y1, top)),
        semantic_role=SemanticRole.MAIN_SHED,
        semantic_confidence=0.85,
    )


def sheds_from_roofs(elements: list[SceneElement], ground: float) -> list[SceneElement]:
    roofs = [item for item in elements if item.semantic_role is SemanticRole.ROOF]
    if not roofs:
        return []
    return [
        _shed_from_cluster(cluster, index, ground)
        for index, cluster in enumerate(roof_clusters(roofs), start=1)
    ]


def _has_overlapping_focus_alternatives(elements: list[SceneElement]) -> bool:
    """Detect mutually exclusive full-building options exported into one IFC scene."""

    sheds = [item for item in elements if item.semantic_role is SemanticRole.MAIN_SHED]
    for index, first in enumerate(sheds):
        first_x0, first_y0, _ = first.bounding_box.minimum
        first_x1, first_y1, _ = first.bounding_box.maximum
        first_area = (first_x1 - first_x0) * (first_y1 - first_y0)
        for second in sheds[index + 1 :]:
            second_x0, second_y0, _ = second.bounding_box.minimum
            second_x1, second_y1, _ = second.bounding_box.maximum
            second_area = (second_x1 - second_x0) * (second_y1 - second_y0)
            overlap_x = max(0.0, min(first_x1, second_x1) - max(first_x0, second_x0))
            overlap_y = max(0.0, min(first_y1, second_y1) - max(first_y0, second_y0))
            overlap = overlap_x * overlap_y
            if min(first_area, second_area) > 0 and overlap / min(first_area, second_area) >= 0.6:
                return True
    return False


class IfcGeometryProvider:
    name = "ifcopenshell"

    def __init__(self, ifc_path: Path) -> None:
        self._ifc_path = ifc_path
        self.diagnostics: tuple[IfcDiagnostic, ...] = ()

    def extract(self, request: GeometryExtractionRequest) -> CanonicalScene:
        if not self._ifc_path.is_file():
            raise InvalidModelError(f"IFC file does not exist: {self._ifc_path}")
        try:
            model = ifcopenshell.open(str(self._ifc_path))
        except Exception as exc:
            raise InvalidModelError("failed to open IFC model") from exc

        settings = ifcopenshell.geom.settings()  # type: ignore[no-untyped-call]
        settings.set(settings.USE_WORLD_COORDS, True)
        mesh_directory = request.working_directory / "meshes"
        measured: list[_Measured] = []
        elements: list[SceneElement] = []
        surfaces: list[SceneSurface] = []
        diagnostics: list[IfcDiagnostic] = []

        for entity in model.by_type("IfcElement"):
            global_id = getattr(entity, "GlobalId", None)
            if entity.is_a("IfcOpeningElement"):
                # A void, not a thing. Extracting them cost 111 meshes on the
                # measured model and told the classifier nothing.
                diagnostics.append(
                    IfcDiagnostic(entity.id(), entity.is_a(), global_id, "skipped", "opening")
                )
                continue
            representation = getattr(entity, "Representation", None)
            if not representation or not isinstance(global_id, str):
                diagnostics.append(
                    IfcDiagnostic(
                        entity.id(),
                        entity.is_a(),
                        global_id,
                        "skipped",
                        "no 3D representation",
                    )
                )
                continue
            try:
                shape: Any = ifcopenshell.geom.create_shape(settings, entity)
                vertices = np.asarray(shape.geometry.verts, dtype=np.float64).reshape((-1, 3))
                faces = np.asarray(shape.geometry.faces, dtype=np.int32).reshape((-1, 3))
            except Exception:
                diagnostics.append(
                    IfcDiagnostic(
                        entity.id(),
                        entity.is_a(),
                        global_id,
                        "skipped",
                        "tessellation failed",
                    )
                )
                continue
            if vertices.size == 0 or faces.size == 0:
                diagnostics.append(
                    IfcDiagnostic(entity.id(), entity.is_a(), global_id, "skipped", "empty mesh")
                )
                continue

            minimum_array = vertices.min(axis=0)
            maximum_array = vertices.max(axis=0)
            minimum = (
                float(minimum_array[0]),
                float(minimum_array[1]),
                float(minimum_array[2]),
            )
            maximum = (
                float(maximum_array[0]),
                float(maximum_array[1]),
                float(maximum_array[2]),
            )
            bounding_box = BoundingBox(minimum=minimum, maximum=maximum)
            dimensions = (
                maximum[0] - minimum[0],
                maximum[1] - minimum[1],
                maximum[2] - minimum[2],
            )
            entity_name = getattr(entity, "Name", None)
            scene_element_id = f"ifc:{global_id}"
            mesh_name = f"{entity.id()}-{_safe_name(global_id)}.npz"
            mesh_path = mesh_directory / mesh_name
            mesh_path.parent.mkdir(parents=True, exist_ok=True)
            np.savez_compressed(mesh_path, vertices=vertices, faces=faces)

            measured.append(
                _Measured(
                    scene_element_id=scene_element_id,
                    global_id=global_id,
                    ifc_type=entity.is_a(),
                    name=entity_name if isinstance(entity_name, str) else None,
                    mesh_ref=f"meshes/{mesh_name}",
                    bounding_box=bounding_box,
                    dimensions=dimensions,
                )
            )
            diagnostics.append(IfcDiagnostic(entity.id(), entity.is_a(), global_id, "extracted"))

        if not measured:
            raise InvalidModelError("IFC model did not contain tessellatable building elements")

        # Second pass. The roof test asks how high an element sits relative to
        # the building, which is only knowable once every box has been measured.
        site_height = max(item.bounding_box.maximum[2] for item in measured)
        ground = min(item.bounding_box.minimum[2] for item in measured)
        for item in measured:
            role, confidence = _semantic_role(
                item.ifc_type,
                item.dimensions,
                item.name,
                base_height=item.bounding_box.minimum[2],
                site_height=site_height,
            )
            elements.append(
                SceneElement(
                    scene_element_id=item.scene_element_id,
                    source=SourceElementRef(
                        external_id=item.global_id,
                        category=item.ifc_type,
                        type_name=item.name,
                    ),
                    transform=IDENTITY_4X4,
                    mesh_ref=item.mesh_ref,
                    bounding_box=item.bounding_box,
                    semantic_role=role,
                    semantic_confidence=confidence,
                )
            )

        # A LOD200 building arrives as roof planes; the design and camera
        # planners read masses. Resolve the planes into the mass they cover.
        elements.extend(sheds_from_roofs(elements, ground))
        for element in elements:
            surfaces.extend(
                _box_surfaces(
                    element.scene_element_id, element.bounding_box, element.semantic_role
                )
            )
        if _has_overlapping_focus_alternatives(elements):
            raise InvalidModelError(
                "IFC contains overlapping focus-building alternatives; use a view-scoped Revit "
                "export so one coherent 3D option is selected before canonicalization"
            )

        self.diagnostics = tuple(diagnostics)
        scene = CanonicalScene(
            source=request.source,
            coordinate_system=CoordinateSystem(source_to_world=IDENTITY_4X4),
            elements=tuple(elements),
            surfaces=tuple(surfaces),
        )
        atomic_write(
            request.working_directory / "canonical_scene.json",
            scene.model_dump_json(indent=2).encode() + b"\n",
        )
        atomic_write(
            request.working_directory / "diagnostics.json",
            json.dumps(
                [asdict(diagnostic) for diagnostic in diagnostics],
                ensure_ascii=False,
                indent=2,
            ).encode()
            + b"\n",
        )
        return scene
