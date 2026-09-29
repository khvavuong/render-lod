import json
from pathlib import Path

from PIL import Image

from v365_archviz.application.realism_parity import (
    CheckRealismParity,
    correction_prompt,
    record_regeneration,
)
from v365_archviz.errors import ProviderError
from v365_archviz.providers.gemini_realism_judge import RealismVerdict


class _Judge:
    def __init__(self, verdicts: dict[str, RealismVerdict | Exception]) -> None:
        self._verdicts = verdicts
        self.calls: list[tuple[str, Path, Path]] = []

    def compare(self, view_id: str, candidate: Path, reference: Path) -> RealismVerdict:
        self.calls.append((view_id, candidate, reference))
        verdict = self._verdicts[view_id]
        if isinstance(verdict, Exception):
            raise verdict
        return verdict


def _image(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (32, 18), "white").save(path)
    return path


def test_only_clear_failures_are_sent_back(tmp_path: Path) -> None:
    master = _image(tmp_path / "view-01" / "refined.jpg")
    views = {
        view_id: _image(tmp_path / view_id / "refined.jpg")
        for view_id in ("view-02", "view-03", "view-04", "view-05")
    }
    judge = _Judge(
        {
            "view-02": RealismVerdict("view-02", False, False, "", "{}"),
            "view-03": RealismVerdict("view-03", True, False, "plastic cladding", "{}"),
            # No answer is not a failure: it must never trigger a paid retry.
            "view-04": RealismVerdict("view-04", None, None, "", "garbled"),
            "view-05": ProviderError("outage"),
        }
    )
    report = tmp_path / "realism_parity.json"

    result = CheckRealismParity().execute(judge, views, master, report)

    assert result.failed == {"view-03": "plastic cladding"}
    assert all(reference == master for _view, _candidate, reference in judge.calls)
    document = json.loads(report.read_text())
    assert [item["status"] for item in document["views"]] == [
        "pass",
        "fail",
        "unverified",
        "unverified",
    ]

    record_regeneration(report, result.failed)
    marked = {
        item["view_id"]: item.get("regenerated") for item in json.loads(report.read_text())["views"]
    }
    assert marked["view-03"] is True
    assert marked["view-02"] is None


def test_a_less_detailed_view_fails_and_its_note_reaches_the_prompt() -> None:
    verdict = RealismVerdict("view-06", False, True, "soft paving and trees", "{}")

    assert verdict.status == "fail"
    prompt = correction_prompt("BASE", "soft paving and trees")
    assert prompt.startswith("BASE\n\nREALISM PARITY CORRECTION")
    assert "soft paving and trees" in prompt
