"""Run view edits off the request thread and let one reader follow each of them.

An edit takes as long as the provider takes, so the POST that starts it answers
straight away and the browser watches the run over server-sent events. The
events of a finished edit stay readable for a while afterwards: a reader that
arrives late, or reconnects after a dropped connection, gets the whole run
replayed rather than an empty stream and no way to tell what happened.
"""

from __future__ import annotations

import json
import logging
import threading
from collections import OrderedDict
from collections.abc import Callable, Iterator
from typing import Any

logger = logging.getLogger(__name__)

#: How many finished runs stay replayable. Each holds at most one preview image.
_RETAINED_RUNS = 32
#: Seconds between keep-alive comments, so proxies do not close an idle stream.
_KEEPALIVE_SECONDS = 15.0

Publish = Callable[[str, dict[str, Any]], None]


class EditStream:
    """The ordered events of one run, readable while it is still being written."""

    def __init__(self) -> None:
        self._events: list[dict[str, Any]] = []
        self._condition = threading.Condition()
        self._closed = False

    def publish(self, kind: str, payload: dict[str, Any]) -> None:
        event = {"type": kind, **payload}
        with self._condition:
            if self._closed:
                return
            # Previews are large and only the newest one is worth replaying, so a
            # new one takes the place of the last rather than growing the buffer.
            if kind == "partial_image" and self._events and self._events[-1]["type"] == kind:
                self._events[-1] = event
            else:
                self._events.append(event)
            self._condition.notify_all()

    def close(self) -> None:
        with self._condition:
            self._closed = True
            self._condition.notify_all()

    @property
    def closed(self) -> bool:
        with self._condition:
            return self._closed

    def outcome(self) -> tuple[str, str | None]:
        """`running`, `completed` or `failed`, with the failure's message."""

        with self._condition:
            failure = next((e for e in self._events if e["type"] == "error"), None)
            if failure is not None:
                return "failed", str(failure.get("message") or "the edit failed")
            return ("completed" if self._closed else "running"), None

    def read(self) -> Iterator[str]:
        """Every event so far, then each new one, then end when the run is over."""

        index = 0
        while True:
            with self._condition:
                while index >= len(self._events) and not self._closed:
                    self._condition.wait(timeout=_KEEPALIVE_SECONDS)
                    if index >= len(self._events) and not self._closed:
                        break
                if index < len(self._events):
                    batch = self._events[index:]
                    index = len(self._events)
                elif self._closed:
                    batch = None
                else:
                    batch = []
            if batch is None:
                return
            if not batch:
                yield ": keep-alive\n\n"
                continue
            for event in batch:
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


class LocalEditDispatcher:
    """Start each edit on its own thread and keep its stream addressable by id."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._streams: OrderedDict[str, EditStream] = OrderedDict()

    def start(self, edit_id: str, work: Callable[[Publish], None]) -> EditStream:
        stream = EditStream()
        with self._lock:
            if edit_id in self._streams:
                raise ValueError(f"edit {edit_id} is already running")
            self._streams[edit_id] = stream
            while len(self._streams) > _RETAINED_RUNS:
                evicted_id, evicted = self._streams.popitem(last=False)
                if not evicted.closed:
                    # Still running: put it back and drop the next oldest instead.
                    self._streams[evicted_id] = evicted
                    self._streams.move_to_end(evicted_id, last=False)
                    break
        thread = threading.Thread(
            target=self._run,
            args=(edit_id, stream, work),
            name=f"v365-edit-{edit_id[:8]}",
            daemon=True,
        )
        thread.start()
        return stream

    def stream(self, edit_id: str) -> EditStream | None:
        with self._lock:
            return self._streams.get(edit_id)

    @staticmethod
    def _run(edit_id: str, stream: EditStream, work: Callable[[Publish], None]) -> None:
        try:
            work(stream.publish)
        except Exception as exc:
            logger.exception("view edit %s failed", edit_id)
            stream.publish("error", {"message": _safe_message(exc)})
        finally:
            # The last event says the run is over, and a reader that sees it
            # closes rather than reconnecting. Without it the browser cannot
            # tell a finished stream from a dropped one, and `EventSource`
            # reopens for ever — measured at forty reconnects on one run.
            stream.publish("done", {})
            stream.close()


def _safe_message(exc: Exception) -> str:
    """The sentence a caller may see, without leaking a path or a key."""

    text = str(exc).strip()
    return text if text else type(exc).__name__
