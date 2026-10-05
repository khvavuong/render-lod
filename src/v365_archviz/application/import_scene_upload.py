"""Write a Site Forma site plan as a canonical scene package.

The result has the same layout as an IFC-derived scene (`canonical_scene.json`
plus one `.npz` mesh per element), so every later stage — design planning,
camera planning, Blender conditioning — reads it without knowing its source.
The revision is the hash of the upload: the same plan always maps to the same
scene, and a changed plan never overwrites an earlier one.
"""

from __future__ import annotations

import hashlib
import io
import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from v365_archviz.artifacts import atomic_write
from v365_archviz.domain.building_kind import BuildingFeatures, BuildingKind, Compass
from v365_archviz.domain.common import Matrix4x4, Vec3
from v365_archviz.domain.gate import GatePart
from v365_archviz.domain.scene import (
    BoundingBox,
    CanonicalScene,
    CoordinateSystem,
    GeometryProviderKind,
    SceneElement,
    SceneSurface,
    SemanticRole,
    SourceElementRef,
    SourceModelRef,
    SurfaceFrame,
)
from v365_archviz.domain.scene_upload import (
    PLOT_BOUNDARY_ID,
    Point2,
    SceneUpload,
    UploadSurface,
)

IDENTITY: Matrix4x4 = (
    (1.0, 0.0, 0.0, 0.0),
    (0.0, 1.0, 0.0, 0.0),
    (0.0, 0.0, 1.0, 0.0),
    (0.0, 0.0, 0.0, 1.0),
)

#: Context element IDs carry this prefix so a design brief can list them.
CONTEXT_PREFIX = "context-"


@dataclass(frozen=True, slots=True)
class ImportedScene:
    model_revision: str
    scene_path: Path
    scene: CanonicalScene
    created: bool


@dataclass(frozen=True, slots=True)
class _Mesh:
    vertices: list[Vec3]
    faces: list[tuple[int, int, int]]


def scene_upload_revision(upload: SceneUpload) -> str:
    """Sixteen hex characters of the upload's canonical JSON hash."""

    return _upload_digest(upload)[:16]


#: Building fields added after the first uploads: left out of the hash while unset, so an
#: upload that does not use them keeps the revision, and the artifacts, it always had.
_LATER_BUILDING_FIELDS = ("kind", "front", "features")


def _upload_digest(upload: SceneUpload) -> str:
    payload = upload.model_dump(mode="json")
    for building in payload["buildings"]:
        for field in _LATER_BUILDING_FIELDS:
            if building.get(field) is None:
                building.pop(field, None)
    # Scene fields added later, left out the same way while unused.
    if payload.get("plot_boundary") is None:
        payload.pop("plot_boundary", None)
    if not payload.get("gates"):
        payload.pop("gates", None)
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ImportSceneUpload:
    def execute(self, upload: SceneUpload, artifact_dir: Path) -> ImportedScene:
        digest = _upload_digest(upload)
        revision = digest[:16]
        root = artifact_dir / "scenes" / revision
        scene_path = root / "canonical_scene.json"
        if scene_path.is_file():
            scene = CanonicalScene.model_validate_json(scene_path.read_text(encoding="utf-8"))
            return ImportedScene(revision, scene_path, scene, created=False)

        elements: list[SceneElement] = []
        surfaces: list[SceneSurface] = []
        for building in upload.buildings:
            corners = _box_corners(
                building.center, building.width_m, building.length_m, building.rotation_rad
            )
            mesh = _prism(corners, building.base_z, building.base_z + building.height_m)
            elements.append(
                self._element(
                    root,
                    building.id,
                    SemanticRole(building.role),
                    mesh,
                    building.name,
                    storeys=building.floors,
                    kind=building.kind,
                    front=building.front,
                    features=building.features,
                )
            )
            surfaces.extend(
                _ring_surfaces(building.id, corners, building.base_z, building.height_m)
            )
        for context in upload.context_buildings:
            ring = _counter_clockwise(context.footprint)
            element_id = f"{CONTEXT_PREFIX}{context.id}"
            mesh = _prism(ring, 0.0, context.height_m)
            elements.append(self._element(root, element_id, SemanticRole.UNKNOWN, mesh, ""))
            surfaces.extend(_ring_surfaces(element_id, ring, 0.0, context.height_m))
        for surface in upload.surfaces:
            elements.append(
                self._element(root, surface.id, SemanticRole(surface.role), _flat(surface), "")
            )
        if upload.plot_boundary:
            ring = _counter_clockwise(upload.plot_boundary)
            elements.append(
                self._element(
                    root,
                    PLOT_BOUNDARY_ID,
                    SemanticRole.SITE_BOUNDARY,
                    # A hairline under the fence: the fence is built along the outline.
                    _ribbon(ring, 0.05, 0.0, 0.01),
                    "",
                    outline=tuple(ring),
                )
            )
        for gate in upload.gates:
            corners = _box_corners(gate.center, gate.width_m, gate.depth_m, gate.rotation_rad)
            elements.append(
                self._element(
                    root,
                    gate.id,
                    SemanticRole.MAIN_ENTRANCE
                    if gate.role == "main"
                    else SemanticRole.SECONDARY_ENTRANCE,
                    # The opening is a flat pad; the gate itself is its parts.
                    _prism(corners, gate.base_z, gate.base_z + 0.02),
                    gate.name,
                    outline=tuple(corners),
                    gate_parts=gate.parts or None,
                )
            )

        scene = CanonicalScene(
            source=SourceModelRef(
                provider=GeometryProviderKind.LOCAL_FIXTURE,
                project_id=upload.project_id,
                model_id="site-forma",
                version_id=f"sha256:{digest}",
                source_sha256=digest,
            ),
            coordinate_system=CoordinateSystem(source_to_world=IDENTITY),
            elements=tuple(elements),
            surfaces=tuple(surfaces),
        )
        atomic_write(
            root / "site_forma_upload.json",
            upload.model_dump_json(indent=2).encode("utf-8") + b"\n",
        )
        atomic_write(scene_path, scene.model_dump_json(indent=2).encode("utf-8") + b"\n")
        return ImportedScene(revision, scene_path, scene, created=True)

    @staticmethod
    def _element(
        root: Path,
        element_id: str,
        role: SemanticRole,
        mesh: _Mesh,
        name: str,
        storeys: int | None = None,
        kind: BuildingKind | None = None,
        front: Compass | None = None,
        features: BuildingFeatures | None = None,
        outline: tuple[Point2, ...] | None = None,
        gate_parts: tuple[GatePart, ...] | None = None,
    ) -> SceneElement:
        mesh_ref = f"meshes/{element_id}.npz"
        buffer = io.BytesIO()
        np.savez_compressed(
            buffer,
            vertices=np.asarray(mesh.vertices, dtype=np.float64),
            faces=np.asarray(mesh.faces, dtype=np.int64),
        )
        atomic_write(root / mesh_ref, buffer.getvalue())
        xs, ys, zs = zip(*mesh.vertices, strict=True)
        return SceneElement(
            scene_element_id=element_id,
            source=SourceElementRef(
                external_id=element_id, category="site-forma", type_name=name or None
            ),
            transform=IDENTITY,
            mesh_ref=mesh_ref,
            bounding_box=BoundingBox(
                minimum=(min(xs), min(ys), min(zs)), maximum=(max(xs), max(ys), max(zs))
            ),
            semantic_role=role,
            # The editor states every role; nothing here is inferred.
            semantic_confidence=1.0,
            storeys=storeys,
            kind=kind,
            front=front,
            features=features,
            outline=outline,
            gate_parts=gate_parts,
        )


def _box_corners(center: Point2, width: float, length: float, rotation: float) -> list[Point2]:
    """A rectangle turned counter-clockwise about its centre, its corners counter-clockwise."""

    cos, sin = math.cos(rotation), math.sin(rotation)
    half_w, half_l = width / 2, length / 2
    cx, cy = center
    local = ((-half_w, -half_l), (half_w, -half_l), (half_w, half_l), (-half_w, half_l))
    return [(cx + x * cos - y * sin, cy + x * sin + y * cos) for x, y in local]


def _ribbon(ring: list[Point2], width: float, bottom: float, top: float) -> _Mesh:
    """A thin strip along each edge of a closed ring."""

    vertices: list[Vec3] = []
    faces: list[tuple[int, int, int]] = []
    for index, start in enumerate(ring):
        end = ring[(index + 1) % len(ring)]
        length = math.hypot(end[0] - start[0], end[1] - start[1])
        if length < 1e-6:
            continue
        center = ((start[0] + end[0]) / 2, (start[1] + end[1]) / 2)
        rotation = math.atan2(end[1] - start[1], end[0] - start[0])
        strip = _prism(_box_corners(center, length, width, rotation), bottom, top)
        offset = len(vertices)
        faces.extend((a + offset, b + offset, c + offset) for a, b, c in strip.faces)
        vertices.extend(strip.vertices)
    return _Mesh(vertices, faces)


def _signed_area(ring: list[Point2] | tuple[Point2, ...]) -> float:
    return 0.5 * sum(
        ring[i][0] * ring[(i + 1) % len(ring)][1] - ring[(i + 1) % len(ring)][0] * ring[i][1]
        for i in range(len(ring))
    )


def _counter_clockwise(ring: tuple[Point2, ...]) -> list[Point2]:
    points = list(ring)
    if len(points) > 1 and points[0] == points[-1]:
        points.pop()
    return points if _signed_area(points) > 0 else points[::-1]


def _prism(ring: list[Point2], bottom: float, top: float) -> _Mesh:
    """A closed extrusion of a counter-clockwise ring, faces wound outward."""

    count = len(ring)
    vertices: list[Vec3] = [(x, y, bottom) for x, y in ring] + [(x, y, top) for x, y in ring]
    faces: list[tuple[int, int, int]] = []
    for a, b, c in _ear_clip(ring):
        faces.append((count + a, count + b, count + c))
        faces.append((c, b, a))
    for index in range(count):
        following = (index + 1) % count
        faces.append((index, following, count + following))
        faces.append((index, count + following, count + index))
    return _Mesh(vertices, faces)


def _ear_clip(ring: list[Point2]) -> list[tuple[int, int, int]]:
    """Triangulate a simple counter-clockwise polygon."""

    remaining = list(range(len(ring)))
    triangles: list[tuple[int, int, int]] = []

    def cross(o: Point2, a: Point2, b: Point2) -> float:
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    def inside(p: Point2, a: Point2, b: Point2, c: Point2) -> bool:
        return cross(a, b, p) >= 0 and cross(b, c, p) >= 0 and cross(c, a, p) >= 0

    guard = len(remaining) ** 2 + 10
    while len(remaining) > 3 and guard > 0:
        guard -= 1
        for position, current in enumerate(remaining):
            before = remaining[position - 1]
            after = remaining[(position + 1) % len(remaining)]
            a, b, c = ring[before], ring[current], ring[after]
            if cross(a, b, c) <= 0:
                continue
            if any(
                inside(ring[other], a, b, c)
                for other in remaining
                if other not in (before, current, after)
            ):
                continue
            triangles.append((before, current, after))
            remaining.pop(position)
            break
        else:
            break
    if len(remaining) >= 3:
        # A degenerate remainder is fanned rather than dropped, so the roof stays closed.
        triangles.extend(
            (remaining[0], remaining[index], remaining[index + 1])
            for index in range(1, len(remaining) - 1)
        )
    return triangles


def _flat(surface: UploadSurface) -> _Mesh:
    values = surface.vertices
    vertices: list[Vec3] = [
        (values[index], values[index + 1], values[index + 2]) for index in range(0, len(values), 3)
    ]
    faces = [
        (surface.faces[index], surface.faces[index + 1], surface.faces[index + 2])
        for index in range(0, len(surface.faces), 3)
    ]
    return _Mesh(vertices, faces)


def _direction(normal_x: float, normal_y: float) -> str:
    if abs(normal_x) >= abs(normal_y):
        return "east" if normal_x >= 0 else "west"
    return "north" if normal_y >= 0 else "south"


def _ring_surfaces(
    element_id: str, ring: list[Point2], bottom: float, height: float
) -> list[SceneSurface]:
    """One vertical facade surface per edge, named by the side it faces."""

    surfaces: list[SceneSurface] = []
    used: dict[str, int] = {}
    for index, start in enumerate(ring):
        end = ring[(index + 1) % len(ring)]
        dx, dy = end[0] - start[0], end[1] - start[1]
        length = math.hypot(dx, dy)
        if length < 0.5:
            continue
        ux, uy = dx / length, dy / length
        direction = _direction(uy, -ux)
        used[direction] = used.get(direction, 0) + 1
        name = direction if used[direction] == 1 else f"{direction}-{used[direction]}"
        surfaces.append(
            SceneSurface(
                surface_id=f"{element_id}:{name}",
                element_id=element_id,
                frame=SurfaceFrame(
                    origin=(start[0], start[1], bottom),
                    u_axis=(ux, uy, 0.0),
                    v_axis=(0.0, 0.0, 1.0),
                    normal=(uy, -ux, 0.0),
                ),
                width_m=length,
                height_m=height,
            )
        )
    return surfaces


def context_element_ids(scene: CanonicalScene) -> tuple[str, ...]:
    """Neighbouring buildings, which a design brief must treat as context."""

    return tuple(
        element.scene_element_id
        for element in scene.elements
        if element.scene_element_id.startswith(CONTEXT_PREFIX)
        and element.semantic_role is SemanticRole.UNKNOWN
    )


def focus_element_ids(scene: CanonicalScene) -> tuple[str, ...]:
    return tuple(
        element.scene_element_id
        for element in scene.elements
        if element.semantic_role in {SemanticRole.MAIN_SHED, SemanticRole.OFFICE_BLOCK}
    )
