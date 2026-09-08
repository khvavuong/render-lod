"""End-to-end RVT to temporary IFC extraction activity."""

from __future__ import annotations

import io
import json
import zipfile
from dataclasses import dataclass
from pathlib import Path

from v365_archviz.artifacts import atomic_write
from v365_archviz.errors import ProviderError
from v365_archviz.providers.aps.model_derivative import ApsModelDerivativeClient
from v365_archviz.providers.local_rvt import LocalRvtInspector


@dataclass(frozen=True, slots=True)
class IfcExtractionArtifacts:
    ifc_path: Path
    manifest_path: Path
    source_sha256: str


def _ifc_payload(content: bytes) -> bytes:
    if content.lstrip().startswith(b"ISO-10303-21;"):
        return content
    if content.startswith(b"PK"):
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            candidates = [name for name in archive.namelist() if name.lower().endswith(".ifc")]
            if len(candidates) != 1:
                raise ProviderError("APS IFC archive must contain exactly one IFC file")
            info = archive.getinfo(candidates[0])
            if info.file_size > 2 * 1024 * 1024 * 1024:
                raise ProviderError("APS IFC archive exceeds the configured safety limit")
            payload = archive.read(info)
            if payload.lstrip().startswith(b"ISO-10303-21;"):
                return payload
    raise ProviderError("APS derivative is not a valid STEP-encoded IFC payload")


class ExtractIfc:
    def __init__(
        self,
        client: ApsModelDerivativeClient,
        inspector: LocalRvtInspector | None = None,
    ) -> None:
        self._client = client
        self._inspector = inspector or LocalRvtInspector()

    def execute(self, source_path: Path, output_directory: Path) -> IfcExtractionArtifacts:
        inspection = self._inspector.inspect(source_path)
        revision_key = inspection.sha256[:16]
        target = output_directory / "extractions" / revision_key
        ifc_path = target / f"{source_path.stem}.ifc"
        manifest_path = target / "manifest.json"

        self._client.ensure_transient_bucket()
        uploaded = self._client.upload(
            source_path,
            object_key=f"{revision_key}-{source_path.name}",
        )
        self._client.submit_ifc_translation(uploaded.encoded_urn)
        translation = self._client.wait_for_ifc(uploaded.encoded_urn)
        payload = _ifc_payload(self._client.download_derivative(translation))
        atomic_write(ifc_path, payload)

        manifest = {
            "schema_version": "1.0.0",
            "source": {
                "file_name": source_path.name,
                "sha256": inspection.sha256,
                "revit_format": inspection.format_version,
                "size_bytes": inspection.size_bytes,
            },
            "provider": {
                "name": "aps_model_derivative",
                "source_urn": uploaded.encoded_urn,
                "translation_status": translation.status,
            },
            "output": {
                "file_name": ifc_path.name,
                "size_bytes": len(payload),
            },
        }
        atomic_write(
            manifest_path,
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True).encode() + b"\n",
        )
        return IfcExtractionArtifacts(
            ifc_path=ifc_path,
            manifest_path=manifest_path,
            source_sha256=inspection.sha256,
        )
