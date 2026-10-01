"""An aerial whose buildings moved in the frame is caught; one that kept them passes."""

import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from tests.test_design_fidelity import _plan
from tests.test_gemini_provider import _settings
from tests.test_studio import _upload
from v365_archviz.application import run_generation_job
from v365_archviz.application.framing_check import (
    FRAMING_CORRECTION,
    MIN_OVERLAP,
    CheckFraming,
    framing_correction_prompt,
    overlap,
)
from v365_archviz.domain.workflow import Camera, ViewRole, ViewSet
from v365_archviz.errors import ProviderError
from v365_archviz.providers.gemini_framing_judge import Box, GeminiFramingJudge

#: The real method; conftest stubs it so no other test calls Gemini.
HOLD_FRAMING = run_generation_job.RunGenerationJob._hold_framing

SHED: Box = (300, 100, 600, 500)
OFFICE: Box = (400, 600, 600, 750)


class _Judge:
    def __init__(self, answers: dict[str, object]) -> None:
        self.answers = answers

    def locate(self, render: Path, photograph: Path, count: int):  # type: ignore[no-untyped-def]
        answer = self.answers[photograph.stem]
        if isinstance(answer, Exception):
            raise answer
        return answer


def test_overlap_is_intersection_over_union() -> None:
    assert overlap(SHED, SHED) == 1.0
    assert overlap(SHED, (300, 300, 600, 700)) == pytest.approx(1 / 3)
    assert overlap(SHED, OFFICE) == 0.0


def test_a_moved_camera_fails_a_kept_one_passes_and_silence_is_unverified(tmp_path: Path) -> None:
    moved = ((SHED, OFFICE), ((450, 200, 750, 600), (550, 700, 750, 850)))
    kept = ((SHED, OFFICE), ((310, 110, 610, 510), (400, 600, 600, 750)))
    judge = _Judge({"view-01": kept, "view-02": moved, "view-03": None, "view-04": ProviderError()})
    views = {view: (tmp_path / "base.png", tmp_path / f"{view}.jpg") for view in judge.answers}

    result = CheckFraming().execute(judge, views, 2, tmp_path / "framing.json")

    assert result.failed == ("view-02",)
    report = json.loads(result.report_path.read_text())
    assert report["min_overlap"] == MIN_OVERLAP
    assert [view["status"] for view in report["views"]] == [
        "pass",
        "fail",
        "unverified",
        "unverified",
    ]


def test_the_correction_asks_for_the_base_frame() -> None:
    prompt = framing_correction_prompt("BASE")

    assert prompt == f"BASE\n\n{FRAMING_CORRECTION}"
    assert "same place and size in the frame" in prompt


def _judge(text: str) -> GeminiFramingJudge:
    payload = {"outputs": [{"type": "text", "text": text}]}
    client = httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
    )
    return GeminiFramingJudge(_settings(), client=client)


def test_the_judge_reads_matching_boxes(tmp_path: Path) -> None:
    image = tmp_path / "image.png"
    image.write_bytes(b"\x89PNG")
    answer = '{"a": [[300, 100, 600, 500]], "b": [[310, 110, 610, 510]]}'

    assert _judge(answer).locate(image, image, 1) == (
        ((300.0, 100.0, 600.0, 500.0),),
        ((310.0, 110.0, 610.0, 510.0),),
    )
    # Unequal or malformed answers carry no verdict.
    assert _judge('{"a": [[1, 2, 3, 4]], "b": []}').locate(image, image, 1) is None
    assert _judge('{"a": [[1, 2, 3]], "b": [[1, 2, 3]]}').locate(image, image, 1) is None
    assert _judge("no json").locate(image, image, 1) is None


def test_only_aerials_are_proofed_and_a_moved_one_is_generated_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("V365_ARTIFACT_DIR", str(tmp_path))
    design = _plan(tmp_path, _upload())
    design_path = tmp_path / "design_dna.json"
    design_path.write_text(design.model_dump_json(), encoding="utf-8")  # type: ignore[attr-defined]
    roles = {"view-01": ViewRole.OVERALL, "view-02": ViewRole.DETAIL, "view-03": ViewRole.CONTEXT}
    paths = SimpleNamespace(
        render_root=tmp_path / "renders",
        generated_root=tmp_path / "generated",
        design_dna=design_path,
    )
    for view_id in roles:
        (paths.generated_root / view_id).mkdir(parents=True)
        (paths.generated_root / view_id / "refined.jpg").write_bytes(b"jpg")
    view_set = ViewSet(
        view_set_id="set",
        design_revision="design",
        cameras=tuple(
            Camera(
                view_id=view_id,
                role=role,
                position=(100.0, 100.0, 60.0),
                target=(0.0, 0.0, 0.0),
                focal_length_mm=35.0,
                sensor_width_mm=36.0,
                aspect_ratio="16:9",
            )
            for view_id, role in roles.items()
        ),
    )
    asked: list[tuple[str, int]] = []

    class Judge:
        def __init__(self, _settings: object) -> None:
            pass

        def locate(self, render: Path, photograph: Path, count: int):  # type: ignore[no-untyped-def]
            asked.append((photograph.parent.name, count))
            moved = photograph.parent.name == "view-02"
            return (SHED,), ((700, 600, 900, 900) if moved else SHED,)

    monkeypatch.setattr(run_generation_job, "GeminiFramingJudge", Judge)
    regenerated: list[str] = []

    def regenerate(view_id: str) -> Path:
        regenerated.append(view_id)
        return tmp_path / "manifest.json"

    manifest = HOLD_FRAMING(
        run_generation_job.RunGenerationJob(),
        SimpleNamespace(gemini_api_key="key"),
        paths,
        view_set,
        tuple(roles),
        regenerate,
    )

    # The close view shows too few buildings to place the camera, so it is not asked about.
    assert asked == [
        ("view-01", len(design.roof_assemblies)),
        ("view-02", len(design.roof_assemblies)),
    ]  # type: ignore[attr-defined]
    assert regenerated == ["view-02"]
    assert manifest == tmp_path / "manifest.json"
    report = json.loads((paths.generated_root / "framing.json").read_text())
    assert [view.get("regenerated") for view in report["views"]] == [None, True]
