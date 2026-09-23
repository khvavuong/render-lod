"""The view audit has to fail loudly and never treat silence as approval.

It replaces the deterministic edge screen for the geometry questions that screen could not answer.
Freeing the provider to design the facade makes pixel comparison under the locked mask permanently
ambiguous, so these verdicts carry the weight the edge score used to.
"""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from v365_archviz.application.verify_views import VerifyViews
from v365_archviz.domain.workflow import Camera, ViewRole, ViewSet
from v365_archviz.errors import InvalidModelError
from v365_archviz.providers.gemini_view_judge import ViewVerdict


def _scaffold(tmp_path: Path, view_ids: tuple[str, ...]) -> tuple[Path, Path, Path]:
    render_root = tmp_path / "renders"
    generated_root = tmp_path / "generated"
    for view_id in view_ids:
        (render_root / view_id).mkdir(parents=True)
        (generated_root / view_id).mkdir(parents=True)
        Image.new("RGB", (8, 6), "white").save(render_root / view_id / "base_rgb.png")
        Image.new("RGB", (8, 6), "grey").save(generated_root / view_id / "unbranded_refined.jpg")
    cameras = tuple(
        Camera(
            view_id=view_id,
            role=ViewRole.OVERALL,
            position=(1.0, 1.0, 1.0),
            target=(0.0, 0.0, 0.0),
            focal_length_mm=28,
            sensor_width_mm=36,
            aspect_ratio="16:9",
        )
        for view_id in view_ids
    )
    view_set_path = tmp_path / "view_set.json"
    view_set_path.write_text(
        ViewSet(view_set_id="set", design_revision="rev", cameras=cameras).model_dump_json(),
        encoding="utf-8",
    )
    return render_root, generated_root, view_set_path


def _judge(verdicts: dict[str, ViewVerdict]) -> object:
    return SimpleNamespace(verify=lambda view_id, _base, _gen: verdicts[view_id])


def _verdict(view_id: str, viewpoint, placement, openings=True) -> ViewVerdict:
    return ViewVerdict(view_id, viewpoint, placement, openings, "", "{}")


def test_a_rebuilt_camera_fails(tmp_path: Path) -> None:
    render, generated, view_set = _scaffold(tmp_path, ("view-01",))

    report = VerifyViews().execute(
        _judge({"view-01": _verdict("view-01", "different", True)}),
        render,
        generated,
        view_set,
    )

    assert report.failed_view_ids == ("view-01",)
    assert report.passed is False


def test_a_moved_building_fails_even_when_the_camera_held(tmp_path: Path) -> None:
    """This is the failure the edge screen was supposed to catch and demonstrably did not."""

    render, generated, view_set = _scaffold(tmp_path, ("view-01",))

    report = VerifyViews().execute(
        _judge({"view-01": _verdict("view-01", "same", False)}),
        render,
        generated,
        view_set,
    )

    assert report.failed_view_ids == ("view-01",)


def test_a_pan_or_crop_is_flagged_for_review_rather_than_failed(tmp_path: Path) -> None:
    """A wider crop of the same shot is recoverable; treating it as a rebuild throws away a
    usable image, which is how the previous screen rejected four of six good views."""

    render, generated, view_set = _scaffold(tmp_path, ("view-01",))

    report = VerifyViews().execute(
        _judge({"view-01": _verdict("view-01", "shifted", True)}),
        render,
        generated,
        view_set,
    )

    assert report.review_view_ids == ("view-01",)
    assert report.failed_view_ids == ()


def test_an_unanswered_view_is_never_an_approval(tmp_path: Path) -> None:
    render, generated, view_set = _scaffold(tmp_path, ("view-01",))

    report = VerifyViews().execute(
        _judge({"view-01": _verdict("view-01", None, None)}),
        render,
        generated,
        view_set,
    )

    assert report.unverified_view_ids == ("view-01",)
    assert report.passed is False


def test_a_missing_generated_image_is_an_error_not_a_skip(tmp_path: Path) -> None:
    render, generated, view_set = _scaffold(tmp_path, ("view-01",))
    (generated / "view-01" / "unbranded_refined.jpg").unlink()

    with pytest.raises(InvalidModelError):
        VerifyViews().execute(
            _judge({"view-01": _verdict("view-01", "same", True)}), render, generated, view_set
        )


def test_the_report_records_every_view_and_says_what_a_pass_means(tmp_path: Path) -> None:
    render, generated, view_set = _scaffold(tmp_path, ("view-01", "view-02"))

    report = VerifyViews().execute(
        _judge(
            {
                "view-01": _verdict("view-01", "same", True),
                "view-02": _verdict("view-02", "same", True, openings=False),
            }
        ),
        render,
        generated,
        view_set,
    )
    document = json.loads(report.report_path.read_text(encoding="utf-8"))

    assert [row["view_id"] for row in document["views"]] == ["view-01", "view-02"]
    assert "not a geometry certification" in document["note"]
    # A missing dock is worth a look but does not by itself make the image unusable.
    assert report.review_view_ids == ("view-02",)
