import threading

from v365_archviz.providers.local_dispatcher import LocalGenerationDispatcher


class _BlockingRunner:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()
        self.calls: list[str] = []

    def execute(self, job_id: str) -> None:
        self.calls.append(job_id)
        self.started.set()
        self.release.wait(timeout=2)


def test_local_dispatcher_serializes_and_deduplicates_jobs() -> None:
    runner = _BlockingRunner()
    dispatcher = LocalGenerationDispatcher(runner)  # type: ignore[arg-type]

    assert dispatcher.submit("job-1") is True
    assert runner.started.wait(timeout=1)
    assert dispatcher.submit("job-1") is False

    runner.release.set()
    assert runner.calls == ["job-1"]
