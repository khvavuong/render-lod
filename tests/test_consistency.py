import json
from pathlib import Path

import pytest

from v365_archviz.application.evaluate_consistency import EvaluateConsistency
from v365_archviz.application.plan_repairs import PlanRepairs
from v365_archviz.domain.qa import (
    ConsistencyReport,
    NormalizedRegion,
    QAFinding,
    QAGate,
    QAStatus,
)
from v365_archviz.errors import InvalidModelError


def _technical_report(path: Path, *, failed: bool = False) -> Path:
    findings = (
        [{"severity": "error", "code": "output_missing", "message": "missing"}] if failed else []
    )
    path.write_text(
        json.dumps(
            {
                "project_id": "project",
                "design_revision": "design",
                "views": [{"view_id": "view-01", "findings": findings}],
                "global_findings": [],
            }
        ),
        encoding="utf-8",
    )
    return path


def test_technical_pass_still_requires_visual_review(tmp_path: Path) -> None:
    result = EvaluateConsistency().execute(
        _technical_report(tmp_path / "technical.json"),
        "model",
        "view-set",
    )

    assert result.report.status is QAStatus.REVIEW
    assert {finding.gate for finding in result.report.findings} == {
        QAGate.GEOMETRY,
        QAGate.SEMANTIC,
        QAGate.CROSS_VIEW_APPEARANCE,
        QAGate.AESTHETIC,
    }


def test_technical_error_fails_consistency_report(tmp_path: Path) -> None:
    result = EvaluateConsistency().execute(
        _technical_report(tmp_path / "technical.json", failed=True),
        "model",
        "view-set",
    )

    assert result.report.status is QAStatus.FAIL
    assert result.report.findings[0].gate is QAGate.ARTIFACT_INTEGRITY


def test_repair_plan_is_bounded_and_escalates(tmp_path: Path) -> None:
    finding = QAFinding(
        finding_id="geometry-1",
        gate=QAGate.GEOMETRY,
        status=QAStatus.FAIL,
        code="edge_displacement",
        message="localized wall edge mismatch",
        view_ids=("view-01",),
        repairable=True,
        region=NormalizedRegion(x=0.1, y=0.1, width=0.2, height=0.3),
    )
    report = ConsistencyReport(
        report_id="report",
        project_id="project",
        model_revision="model",
        design_revision="design",
        view_set_id="view-set",
        status=QAStatus.FAIL,
        findings=(finding,),
    )
    report_path = tmp_path / "consistency.json"
    report_path.write_text(report.model_dump_json(), encoding="utf-8")

    local = PlanRepairs().execute(report_path, {"view-01": 1})
    full = PlanRepairs().execute(report_path, {"view-01": 2})
    exhausted = PlanRepairs().execute(report_path, {"view-01": 3})

    assert local.requests[0].strategy.value == "local_inpaint"
    assert local.requests[0].attempt == 2
    assert full.requests[0].strategy.value == "full_regeneration"
    assert full.requests[0].region is None
    assert exhausted.requests == ()
    assert exhausted.exhausted_view_ids == ("view-01",)

    with pytest.raises(InvalidModelError, match="non-negative integers"):
        PlanRepairs().execute(report_path, {"view-01": -1})
