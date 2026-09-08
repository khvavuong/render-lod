"""Build a canonical scene package from an APS-derived IFC artifact."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from v365_archviz.domain.scene import GeometryProviderKind, SourceModelRef
from v365_archviz.providers.contracts import GeometryExtractionRequest
from v365_archviz.providers.ifc import IfcGeometryProvider
from v365_archviz.providers.local_rvt import LocalRvtInspector


@dataclass(frozen=True, slots=True)
class CanonicalSceneArtifacts:
    scene_path: Path
    diagnostics_path: Path
    mesh_directory: Path
    element_count: int
    surface_count: int


class BuildCanonicalScene:
    def execute(
        self,
        source_rvt: Path,
        ifc_path: Path,
        output_directory: Path,
    ) -> CanonicalSceneArtifacts:
        inspection = LocalRvtInspector().inspect(source_rvt)
        target = output_directory / "scenes" / inspection.sha256[:16]
        source = SourceModelRef(
            provider=GeometryProviderKind.MODEL_DERIVATIVE,
            project_id="aps-oss",
            model_id=source_rvt.name,
            version_id=f"sha256:{inspection.sha256}",
            source_sha256=inspection.sha256,
        )
        provider = IfcGeometryProvider(ifc_path)
        scene = provider.extract(
            GeometryExtractionRequest(source=source, working_directory=target)
        )
        return CanonicalSceneArtifacts(
            scene_path=target / "canonical_scene.json",
            diagnostics_path=target / "diagnostics.json",
            mesh_directory=target / "meshes",
            element_count=len(scene.elements),
            surface_count=len(scene.surfaces),
        )

