"""Durable record of every human-directed edit made to a refined view.

A view keeps exactly one current image, because `_output_files`,
`_refined_image` and `ProtectRefinement` each fail on a directory holding two
`refined.*` files. So versions go down one level instead of sideways:

    view-03/
      refined.png            the current image, named as every consumer expects
      edits/
        manifest.json        append-only; the last committed record is current
        0001/request.json    prompt, options, provider request id, who, when
        0001/mask.png        what the person drew, kept as evidence
        0001/previous.png    the image this edit replaced
        0001/candidates/     what the provider offered, before one was chosen

Nothing here is ever rewritten or deleted. Restoring an older image appends a
new record whose own `previous` is the image being replaced, so the log reads
forward and the way back is always one more step, never an erasure.
"""

from __future__ import annotations

import json
import mimetypes
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from v365_archviz.artifacts import atomic_write
from v365_archviz.domain.common import utc_now
from v365_archviz.errors import InvalidModelError

MANIFEST_NAME = "manifest.json"
EDITS_DIRNAME = "edits"
SCHEMA_VERSION = "1.0.0"

#: A pending edit is one whose candidates exist but none has been chosen yet.
STATE_PENDING = "pending"
STATE_COMMITTED = "committed"


@dataclass(frozen=True, slots=True)
class ViewEditRecord:
    """One entry of a view's edit log, as stored and as served."""

    edit_id: str
    view_id: str
    sequence: int
    kind: str
    state: str
    prompt: str
    candidate_count: int
    chosen: int | None
    created_by: str
    created_at: str
    committed_at: str | None
    provider_request_id: str | None

    def as_document(self) -> dict[str, Any]:
        return {
            "edit_id": self.edit_id,
            "view_id": self.view_id,
            "sequence": self.sequence,
            "kind": self.kind,
            "state": self.state,
            "prompt": self.prompt,
            "candidate_count": self.candidate_count,
            "chosen": self.chosen,
            "created_by": self.created_by,
            "created_at": self.created_at,
            "committed_at": self.committed_at,
            "provider_request_id": self.provider_request_id,
        }

    @classmethod
    def from_document(cls, document: dict[str, Any]) -> ViewEditRecord:
        return cls(
            edit_id=str(document["edit_id"]),
            view_id=str(document["view_id"]),
            sequence=int(document["sequence"]),
            kind=str(document.get("kind", "edit")),
            state=str(document.get("state", STATE_COMMITTED)),
            prompt=str(document.get("prompt", "")),
            candidate_count=int(document.get("candidate_count", 1)),
            chosen=(
                int(document["chosen"]) if isinstance(document.get("chosen"), int) else None
            ),
            created_by=str(document.get("created_by", "")),
            created_at=str(document.get("created_at", "")),
            committed_at=(
                str(document["committed_at"])
                if isinstance(document.get("committed_at"), str)
                else None
            ),
            provider_request_id=(
                str(document["provider_request_id"])
                if isinstance(document.get("provider_request_id"), str)
                else None
            ),
        )


class ViewEditStore:
    """Read and append one view's edit log without ever losing an earlier image."""

    def __init__(self, view_directory: Path) -> None:
        self.view_directory = view_directory
        self.edits_root = view_directory / EDITS_DIRNAME

    # -- reading ---------------------------------------------------------

    @property
    def manifest_path(self) -> Path:
        return self.edits_root / MANIFEST_NAME

    def records(self) -> tuple[ViewEditRecord, ...]:
        if not self.manifest_path.is_file():
            return ()
        try:
            document = json.loads(self.manifest_path.read_text(encoding="utf-8"))
            entries = document["edits"]
        except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
            raise InvalidModelError(f"edit log is unreadable: {self.manifest_path}") from exc
        if not isinstance(entries, list):
            raise InvalidModelError(f"edit log is unreadable: {self.manifest_path}")
        return tuple(ViewEditRecord.from_document(entry) for entry in entries)

    def record(self, edit_id: str) -> ViewEditRecord:
        for candidate in self.records():
            if candidate.edit_id == edit_id:
                return candidate
        raise InvalidModelError(f"no edit {edit_id} on {self.view_directory.name}")

    def current_image(self) -> Path:
        """The view's one refined image, whatever extension it was written with."""

        images = tuple(
            path
            for path in self.view_directory.glob("refined.*")
            if path.is_file() and path.suffix.lower() != ".json"
        )
        if len(images) != 1:
            raise InvalidModelError(
                f"{self.view_directory.name} has no unique refined image to edit"
            )
        return images[0]

    def directory_of(self, record: ViewEditRecord) -> Path:
        return self.edits_root / f"{record.sequence:04d}"

    def previous_image(self, record: ViewEditRecord) -> Path:
        directory = self.directory_of(record)
        images = tuple(path for path in directory.glob("previous.*") if path.is_file())
        if len(images) != 1:
            raise InvalidModelError(f"edit {record.edit_id} kept no replaced image")
        return images[0]

    def candidate_image(self, record: ViewEditRecord, index: int) -> Path:
        directory = self.directory_of(record) / "candidates"
        images = tuple(path for path in directory.glob(f"{index:03d}.*") if path.is_file())
        if len(images) != 1:
            raise InvalidModelError(f"edit {record.edit_id} has no candidate {index}")
        return images[0]

    # -- writing ---------------------------------------------------------

    def next_sequence(self) -> int:
        existing = self.records()
        return (max((record.sequence for record in existing), default=0)) + 1

    def open_record(
        self,
        *,
        edit_id: str,
        view_id: str,
        kind: str,
        prompt: str,
        candidates: tuple[bytes, ...],
        mask: bytes | None,
        request: dict[str, Any],
        created_by: str,
        provider_request_id: str | None,
    ) -> ViewEditRecord:
        """Store what the provider produced and log it as pending, touching nothing current."""

        sequence = self.next_sequence()
        directory = self.edits_root / f"{sequence:04d}"
        for index, content in enumerate(candidates):
            atomic_write(directory / "candidates" / f"{index:03d}.png", content)
        if mask is not None:
            atomic_write(directory / "mask.png", mask)
        record = ViewEditRecord(
            edit_id=edit_id,
            view_id=view_id,
            sequence=sequence,
            kind=kind,
            state=STATE_PENDING,
            prompt=prompt,
            candidate_count=len(candidates),
            chosen=None,
            created_by=created_by,
            created_at=utc_now().isoformat(),
            committed_at=None,
            provider_request_id=provider_request_id,
        )
        atomic_write(
            directory / "request.json",
            _encode({"schema_version": SCHEMA_VERSION, **request, **record.as_document()}),
        )
        self._append(record)
        return record

    def commit_record(self, record: ViewEditRecord, *, chosen: int) -> ViewEditRecord:
        """Make one candidate the view's current image, keeping the one it replaces."""

        if record.state != STATE_PENDING:
            raise InvalidModelError(f"edit {record.edit_id} was already decided")
        if chosen < 0 or chosen >= record.candidate_count:
            raise InvalidModelError(f"edit {record.edit_id} has no candidate {chosen}")
        source = self.candidate_image(record, chosen)
        self._replace_current(source.read_bytes(), source.suffix, record)
        committed = ViewEditRecord(
            **{
                **_fields(record),
                "state": STATE_COMMITTED,
                "chosen": chosen,
                "committed_at": utc_now().isoformat(),
            }
        )
        self._rewrite(committed)
        return committed

    def restore_record(
        self,
        source_record: ViewEditRecord,
        *,
        edit_id: str,
        created_by: str,
    ) -> ViewEditRecord:
        """Bring an earlier image back as a new entry, never by deleting a later one."""

        source = self.previous_image(source_record)
        content = source.read_bytes()
        sequence = self.next_sequence()
        record = ViewEditRecord(
            edit_id=edit_id,
            view_id=source_record.view_id,
            sequence=sequence,
            kind="restore",
            state=STATE_COMMITTED,
            prompt=f"khôi phục ảnh trước lần sửa {source_record.sequence:04d}",
            candidate_count=1,
            chosen=0,
            created_by=created_by,
            created_at=utc_now().isoformat(),
            committed_at=utc_now().isoformat(),
            provider_request_id=None,
        )
        directory = self.edits_root / f"{sequence:04d}"
        atomic_write(directory / "candidates" / f"000{source.suffix}", content)
        atomic_write(
            directory / "request.json",
            _encode(
                {
                    "schema_version": SCHEMA_VERSION,
                    "restored_from": source_record.edit_id,
                    "restored_from_sequence": source_record.sequence,
                    **record.as_document(),
                }
            ),
        )
        self._append(record)
        self._replace_current(content, source.suffix, record)
        return record

    def fail_record(self, record: ViewEditRecord, message: str) -> None:
        directory = self.directory_of(record)
        atomic_write(directory / "error.json", _encode({"error": message}))

    # -- internals -------------------------------------------------------

    def _replace_current(self, content: bytes, suffix: str, record: ViewEditRecord) -> None:
        """Swap the current image, archiving it first and keeping the file unique.

        The new name may differ from the old one — an edit comes back as PNG even
        where the view was a JPEG. The old file is unlinked after the new one is
        written, the same order `ProtectRefinement` uses, so a crash leaves a
        readable directory rather than none at all.
        """

        current = self.current_image()
        archived = self.directory_of(record) / f"previous{current.suffix}"
        if not archived.is_file():
            atomic_write(archived, current.read_bytes())
        target = self.view_directory / f"refined{suffix.lower()}"
        atomic_write(target, content)
        if current != target:
            current.unlink(missing_ok=True)

    def _append(self, record: ViewEditRecord) -> None:
        self._write_all((*self.records(), record))

    def _rewrite(self, record: ViewEditRecord) -> None:
        self._write_all(
            tuple(
                record if existing.edit_id == record.edit_id else existing
                for existing in self.records()
            )
        )

    def _write_all(self, records: tuple[ViewEditRecord, ...]) -> None:
        atomic_write(
            self.manifest_path,
            _encode(
                {
                    "schema_version": SCHEMA_VERSION,
                    "view_id": self.view_directory.name,
                    "edits": [record.as_document() for record in records],
                }
            ),
        )


def media_type_of(path: Path) -> str:
    return mimetypes.guess_type(path.name)[0] or "application/octet-stream"


def _fields(record: ViewEditRecord) -> dict[str, Any]:
    return {field: getattr(record, field) for field in ViewEditRecord.__slots__}


def _encode(document: dict[str, Any]) -> bytes:
    return json.dumps(document, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
