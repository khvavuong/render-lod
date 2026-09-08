"""Read safe metadata and embedded preview from a local RVT file.

This adapter intentionally does not claim to extract geometry. RVT geometry must
flow through an Autodesk-backed provider or a supported export.
"""

from __future__ import annotations

import hashlib
import io
import re
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree

import olefile

from v365_archviz.errors import InvalidModelError

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
PNG_END = b"IEND"


@dataclass(frozen=True)
class RvtInspection:
    path: Path
    size_bytes: int
    sha256: str
    format_version: str | None
    build: str | None
    worksharing: str | None
    last_save_path: str | None
    document_guid: str | None
    title: str | None
    project_name: str | None
    total_area: str | None
    updated_at: datetime | None
    external_reference_count: int
    preview_png: bytes | None

    def to_manifest(self) -> dict[str, object]:
        return {
            "schema_version": "1.0.0",
            "source": {
                "file_name": self.path.name,
                "size_bytes": self.size_bytes,
                "sha256": self.sha256,
                "format_version": self.format_version,
                "build": self.build,
                "document_guid": self.document_guid,
            },
            "project": {
                "title": self.title,
                "project_name": self.project_name,
                "total_area": self.total_area,
                "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            },
            "diagnostics": {
                "worksharing": self.worksharing,
                "external_reference_count": self.external_reference_count,
                "has_preview": self.preview_png is not None,
            },
        }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _find_line(text: str, label: str) -> str | None:
    match = re.search(rf"{re.escape(label)}\s*([^\r\n\x00]+)", text)
    return match.group(1).strip() if match else None


def _utf16_lines(payload: bytes) -> str:
    """Recover aligned printable UTF-16LE runs from mixed binary streams."""
    runs = re.findall(rb"(?:[\x20-\x7e]\x00){4,}", payload)
    return "\n".join(run.decode("utf-16le") for run in runs)


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _project_fields(payload: bytes) -> dict[str, str | datetime | None]:
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        members = archive.namelist()
        if not members:
            return {}
        root = ElementTree.fromstring(archive.read(members[0]))

    result: dict[str, str | datetime | None] = {}
    for element in root.iter():
        name = _local_name(element.tag)
        if name == "title" and "title" not in result:
            result["title"] = element.text
        elif name == "updated" and element.text:
            result["updated_at"] = datetime.fromisoformat(element.text.replace("Z", "+00:00"))
        elif name == "Project_Name":
            result["project_name"] = element.text
        elif name == "Tổng_diện_tích":
            result["total_area"] = element.text
    return result


def _extract_preview(payload: bytes) -> bytes | None:
    start = payload.find(PNG_SIGNATURE)
    end_marker = payload.find(PNG_END, start)
    if start < 0 or end_marker < 0:
        return None
    return payload[start : end_marker + len(PNG_END) + 4]


def _optional_string(value: str | datetime | None) -> str | None:
    return value if isinstance(value, str) else None


def _optional_datetime(value: str | datetime | None) -> datetime | None:
    return value if isinstance(value, datetime) else None


class LocalRvtInspector:
    """Inspect an RVT envelope without launching Revit."""

    def inspect(self, path: Path) -> RvtInspection:
        resolved = path.resolve()
        if not resolved.is_file():
            raise InvalidModelError(f"RVT file does not exist: {path}")
        if resolved.suffix.lower() != ".rvt":
            raise InvalidModelError(f"expected an .rvt file: {path}")
        if not olefile.isOleFile(str(resolved)):
            raise InvalidModelError(f"file is not a supported RVT container: {path}")

        try:
            with olefile.OleFileIO(str(resolved)) as container:
                required = {"BasicFileInfo", "ProjectInformation"}
                available = {"/".join(parts) for parts in container.listdir()}
                missing = required - available
                if missing:
                    raise InvalidModelError(f"RVT is missing streams: {sorted(missing)}")
                basic = _utf16_lines(container.openstream("BasicFileInfo").read())
                project = _project_fields(container.openstream("ProjectInformation").read())
                transmission = (
                    container.openstream("TransmissionData").read()
                    if container.exists("TransmissionData")
                    else b""
                )
                preview = (
                    _extract_preview(container.openstream("RevitPreview4.0").read())
                    if container.exists("RevitPreview4.0")
                    else None
                )
        except (OSError, ValueError, zipfile.BadZipFile, ElementTree.ParseError) as exc:
            raise InvalidModelError(f"failed to inspect RVT: {exc}") from exc

        return RvtInspection(
            path=resolved,
            size_bytes=resolved.stat().st_size,
            sha256=_sha256(resolved),
            format_version=_find_line(basic, "Format:"),
            build=_find_line(basic, "Build:"),
            worksharing=_find_line(basic, "Worksharing:"),
            last_save_path=_find_line(basic, "Last Save Path:"),
            document_guid=_find_line(basic, "Unique Document GUID:"),
            title=_optional_string(project.get("title")),
            project_name=_optional_string(project.get("project_name")),
            total_area=_optional_string(project.get("total_area")),
            updated_at=_optional_datetime(project.get("updated_at")),
            external_reference_count=transmission.count(
                "<ExternalFileReference>".encode("utf-16le")
            ),
            preview_png=preview,
        )
