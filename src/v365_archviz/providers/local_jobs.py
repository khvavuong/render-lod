"""Atomic local metadata repository used by development and single-node deployments."""

from __future__ import annotations

import fcntl
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from v365_archviz.artifacts import atomic_write
from v365_archviz.domain.jobs import GenerationJob


class LocalJobRepository:
    def __init__(self, root: Path) -> None:
        self._root = root

    @contextmanager
    def _lock(self) -> Iterator[None]:
        self._root.mkdir(parents=True, exist_ok=True)
        lock_path = self._root / ".lock"
        with lock_path.open("a+b") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def create_or_get(self, job: GenerationJob) -> tuple[GenerationJob, bool]:
        with self._lock():
            idempotency_path = self._root / "idempotency" / job.idempotency_key
            if idempotency_path.is_file():
                existing_id = idempotency_path.read_text(encoding="utf-8").strip()
                return self.get(existing_id), False
            self._write(job)
            atomic_write(idempotency_path, f"{job.job_id}\n".encode())
            atomic_write(
                self._root / "view_sets" / job.view_set_id,
                f"{job.job_id}\n".encode(),
            )
            return job, True

    def get(self, job_id: str) -> GenerationJob:
        path = self._root / "jobs" / f"{job_id}.json"
        return GenerationJob.model_validate_json(path.read_text(encoding="utf-8"))

    def get_by_view_set(self, view_set_id: str) -> GenerationJob:
        index = self._root / "view_sets" / view_set_id
        job_id = index.read_text(encoding="utf-8").strip()
        return self.get(job_id)

    def save(self, job: GenerationJob) -> None:
        with self._lock():
            self._write(job)

    def _write(self, job: GenerationJob) -> None:
        atomic_write(
            self._root / "jobs" / f"{job.job_id}.json",
            job.model_dump_json(indent=2).encode() + b"\n",
        )
