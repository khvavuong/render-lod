"""A rejected camera must be re-derived, not re-rendered unchanged and not silently shipped."""

import json
from pathlib import Path

import pytest

from v365_archviz.application.repair_conditioning import (
    REPAIR_BEARING_OFFSETS_DEG,
    failed_view_ids,
    merge_repaired_views,
)
from v365_archviz.domain.workflow import Camera, ViewRole, ViewSet


def _camera(view_id: str, role: ViewRole, x: float) -> Camera:
    return Camera(
        view_id=view_id,
        role=role,
        position=(x, 0.0, 10.0),
        target=(0.0, 0.0, 1.0),
        focal_length_mm=28,
        sensor_width_mm=36,
        aspect_ratio="16:9",
    )


def _view_set(cameras: tuple[Camera, ...]) -> ViewSet:
    return ViewSet(view_set_id="set", design_revision="rev", cameras=cameras)


def test_only_rejected_views_are_read_out_of_the_report(tmp_path: Path) -> None:
    report = tmp_path / "conditioning_qa.json"
    report.write_text(
        json.dumps(
            {
                "views": [
                    {"view_id": "view-01", "status": "pass"},
                    {"view_id": "view-02", "status": "fail"},
                    {"view_id": "view-03", "status": "fail"},
                ]
            }
        ),
        encoding="utf-8",
    )

    assert failed_view_ids(report) == ("view-02", "view-03")


def test_a_missing_report_is_not_an_approval(tmp_path: Path) -> None:
    """Treating an absent gate result as a pass is how unusable cameras reach paid generation."""

    with pytest.raises(FileNotFoundError):
        failed_view_ids(tmp_path / "conditioning_qa.json")


def test_accepted_views_keep_their_cameras(tmp_path: Path) -> None:
    """Replacing the whole set costs five renders to fix one and moves views already approved."""

    current = _view_set(
        (
            _camera("view-01", ViewRole.OVERALL, 100.0),
            _camera("view-02", ViewRole.CONTEXT, 200.0),
        )
    )
    replanned = _view_set(
        (
            _camera("view-01", ViewRole.OVERALL, 111.0),
            _camera("view-02", ViewRole.CONTEXT, 222.0),
        )
    )

    merged = merge_repaired_views(current, replanned, ("view-02",))

    by_id = {camera.view_id: camera for camera in merged.cameras}
    assert by_id["view-01"].position[0] == pytest.approx(100.0)
    assert by_id["view-02"].position[0] == pytest.approx(222.0)


def test_the_view_order_and_set_identity_survive_a_repair() -> None:
    current = _view_set(
        (
            _camera("view-01", ViewRole.OVERALL, 1.0),
            _camera("view-02", ViewRole.CONTEXT, 2.0),
            _camera("view-03", ViewRole.HERO, 3.0),
        )
    )
    replanned = _view_set((_camera("view-02", ViewRole.CONTEXT, 20.0),))

    merged = merge_repaired_views(current, replanned, ("view-02",))

    assert [camera.view_id for camera in merged.cameras] == ["view-01", "view-02", "view-03"]
    assert merged.view_set_id == current.view_set_id
    assert merged.design_revision == current.design_revision


def test_the_repair_sequence_is_fixed_so_the_same_import_repairs_the_same_way() -> None:
    assert REPAIR_BEARING_OFFSETS_DEG[0] == pytest.approx(35.0)
    # Alternating sides, or a second attempt walks into the first attempt's obstruction.
    assert all(
        REPAIR_BEARING_OFFSETS_DEG[index] * REPAIR_BEARING_OFFSETS_DEG[index + 1] < 0
        for index in range(len(REPAIR_BEARING_OFFSETS_DEG) - 2)
    )
