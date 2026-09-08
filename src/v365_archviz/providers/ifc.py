"""IFC to Canonical Scene provider using IfcOpenShell tessellation."""

from __future__ import annotations

import json
import re
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


def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", value)


def _semantic_role(
    entity_type: str,
    dimensions: tuple[float, float, float],
    name: str | None = None,
) -> tuple[SemanticRole, float]:
    width, depth, height = dimensions
    footprint_area = width * depth
    normalized_name = (name or "").casefold()
    if height <= 0.5 and footprint_area >= 500:
        return SemanticRole.SERVICE_YARD, 0.75
    if entity_type == "IfcBuildingElementProxy" and footprint_area >= 500 and height >= 5:
        return SemanticRole.MAIN_SHED, 0.9
    if 80 <= footprint_area < 500 and height >= 8:
        confidence = 0.9 if "2 tầng" in normalized_name else 0.8
        return SemanticRole.OFFICE_BLOCK, confidence
    if 20 <= footprint_area < 500 and height >= 3:
        return SemanticRole.UTILITY_BLOCK, 0.65
    return SemanticRole.UNKNOWN, 0.4


def _box_surfaces(
    element_id: str,
    bounding_box: BoundingBox,
) -> tuple[SceneSurface, ...]:
    x0, y0, z0 = bounding_box.minimum
    x1, y1, z1 = bounding_box.maximum
    width = x1 - x0
    depth = y1 - y0
    height = z1 - z0
    if width <= 0 or depth <= 0 or height <= 0:
        return ()
    if height < 3.0:
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
            semantic_role=SemanticRole.UNKNOWN,
        )
        for name, origin, u_axis, normal, surface_width in definitions
    )


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
        elements: list[SceneElement] = []
        surfaces: list[SceneSurface] = []
        diagnostics: list[IfcDiagnostic] = []

        for entity in model.by_type("IfcElement"):
            global_id = getattr(entity, "GlobalId", None)
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
            role, confidence = _semantic_role(
                entity.is_a(), dimensions, entity_name if isinstance(entity_name, str) else None
            )
            scene_element_id = f"ifc:{global_id}"
            mesh_name = f"{entity.id()}-{_safe_name(global_id)}.npz"
            mesh_path = mesh_directory / mesh_name
            mesh_path.parent.mkdir(parents=True, exist_ok=True)
            np.savez_compressed(mesh_path, vertices=vertices, faces=faces)

            element = SceneElement(
                scene_element_id=scene_element_id,
                source=SourceElementRef(
                    external_id=global_id,
                    category=entity.is_a(),
                    type_name=entity_name if isinstance(entity_name, str) else None,
                ),
                transform=IDENTITY_4X4,
                mesh_ref=f"meshes/{mesh_name}",
                bounding_box=bounding_box,
                semantic_role=role,
                semantic_confidence=confidence,
            )
            elements.append(element)
            surfaces.extend(_box_surfaces(scene_element_id, bounding_box))
            diagnostics.append(IfcDiagnostic(entity.id(), entity.is_a(), global_id, "extracted"))

        if not elements:
            raise InvalidModelError("IFC model did not contain tessellatable building elements")

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
