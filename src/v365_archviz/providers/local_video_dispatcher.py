"""Background dispatcher dedicated to opt-in video jobs."""

from __future__ import annotations

import logging
import queue
import threading

from v365_archviz.application.run_video_job import RunVideoJob

logger = logging.getLogger(__name__)


class LocalVideoDispatcher:
    def __init__(self, runner: RunVideoJob | None = None) -> None:
        self._runner = runner or RunVideoJob()
        self._queue: queue.Queue[str] = queue.Queue()
        self._lock = threading.Lock()
        self._scheduled: set[str] = set()
        self._thread = threading.Thread(
            target=self._consume, name="v365-video-worker", daemon=True
        )
        self._thread.start()

    def submit(self, video_job_id: str) -> bool:
        with self._lock:
            if video_job_id in self._scheduled:
                return False
            self._scheduled.add(video_job_id)
        self._queue.put(video_job_id)
        return True

    def _consume(self) -> None:
        while True:
            video_job_id = self._queue.get()
            try:
                self._runner.execute(video_job_id)
            except Exception:
                logger.exception("unhandled dispatcher failure for %s", video_job_id)
            finally:
                with self._lock:
                    self._scheduled.discard(video_job_id)
                self._queue.task_done()
