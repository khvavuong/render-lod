"""Single-process background dispatcher for local and development deployments."""

from __future__ import annotations

import logging
import queue
import threading

from v365_archviz.application.run_generation_job import RunGenerationJob

logger = logging.getLogger(__name__)


class LocalGenerationDispatcher:
    """Serialize expensive local jobs without blocking HTTP request threads."""

    def __init__(self, runner: RunGenerationJob | None = None) -> None:
        self._runner = runner or RunGenerationJob()
        self._queue: queue.Queue[str] = queue.Queue()
        self._lock = threading.Lock()
        self._scheduled: set[str] = set()
        self._thread = threading.Thread(
            target=self._consume,
            name="v365-generation-worker",
            daemon=True,
        )
        self._thread.start()

    def submit(self, job_id: str) -> bool:
        with self._lock:
            if job_id in self._scheduled:
                return False
            self._scheduled.add(job_id)
        self._queue.put(job_id)
        return True

    def _consume(self) -> None:
        while True:
            job_id = self._queue.get()
            try:
                self._runner.execute(job_id)
            except Exception:
                logger.exception("unhandled dispatcher failure for %s", job_id)
            finally:
                with self._lock:
                    self._scheduled.discard(job_id)
                self._queue.task_done()
