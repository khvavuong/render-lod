"""Use case for reproducible, non-destructive source-model inspection."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from v365_archviz.artifacts import atomic_write
from v365_archviz.providers.local_rvt import LocalRvtInspector, RvtInspection


@dataclass(frozen=True)
class InspectionArtifacts:
    manifest_path: Path
    preview_path: Path | None
    inspection: RvtInspection


class InspectModel:
    def __init__(self, inspector: LocalRvtInspector | None = None) -> None:
        self._inspector = inspector or LocalRvtInspector()

    def execute(self, source_path: Path, output_directory: Path) -> InspectionArtifacts:
        inspection = self._inspector.inspect(source_path)
        revision_key = inspection.sha256[:16]
        target = output_directory / "inspections" / revision_key
        manifest_path = target / "manifest.json"
        manifest = json.dumps(
            inspection.to_manifest(), ensure_ascii=False, indent=2, sort_keys=True
        ).encode("utf-8")
        atomic_write(manifest_path, manifest + b"\n")

        preview_path = None
        if inspection.preview_png:
            preview_path = target / "preview.png"
            atomic_write(preview_path, inspection.preview_png)

        return InspectionArtifacts(
            manifest_path=manifest_path,
            preview_path=preview_path,
            inspection=inspection,
        )
