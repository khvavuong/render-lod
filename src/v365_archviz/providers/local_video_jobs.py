"""Atomic metadata repository for independent video jobs."""

from __future__ import annotations

import os
import re
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from v365_archviz.artifacts import atomic_write
from v365_archviz.domain.video_jobs import VideoJob

if os.name == "nt":
    import msvcrt
else:
    import fcntl

_SAFE_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,255}$")


def _storage_key(value: str) -> str:
    if not _SAFE_KEY.fullmatch(value):
        raise ValueError("unsafe video metadata storage key")
    return value


class LocalVideoJobRepository:
    def __init__(self, root: Path) -> None:
        self._root = root

    @contextmanager
    def _lock(self) -> Iterator[None]:
        self._root.mkdir(parents=True, exist_ok=True)
        with (self._root / ".video.lock").open("a+b") as handle:
            if os.name == "nt":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                if os.name == "nt":
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def create_or_get(self, job: VideoJob) -> tuple[VideoJob, bool]:
        with self._lock():
            index = self._root / "video_idempotency" / _storage_key(job.idempotency_key)
            if index.is_file():
                return self.get(index.read_text(encoding="utf-8").strip()), False
            self._write(job)
            atomic_write(index, f"{job.video_job_id}\n".encode())
            return job, True

    def get(self, video_job_id: str) -> VideoJob:
        path = self._root / "video_jobs" / f"{_storage_key(video_job_id)}.json"
        return VideoJob.model_validate_json(path.read_text(encoding="utf-8"))

    def save(self, job: VideoJob) -> None:
        with self._lock():
            self._write(job)

    def _write(self, job: VideoJob) -> None:
        atomic_write(
            self._root / "video_jobs" / f"{_storage_key(job.video_job_id)}.json",
            job.model_dump_json(indent=2).encode() + b"\n",
        )
