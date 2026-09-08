import pytest
from pydantic import ValidationError

from v365_archviz.domain.qa import (
    ConsistencyReport,
    NormalizedRegion,
    QAFinding,
    QAGate,
    QAStatus,
    RepairRequest,
    RepairStrategy,
)


def test_passing_report_cannot_hide_failed_finding() -> None:
    finding = QAFinding(
        finding_id="finding-1",
        gate=QAGate.GEOMETRY,
        status=QAStatus.FAIL,
        code="silhouette_iou",
        message="silhouette is outside tolerance",
        view_ids=("view-01",),
        score=0.8,
        threshold=0.97,
        repairable=True,
    )

    with pytest.raises(ValidationError, match="passing report"):
        ConsistencyReport(
            report_id="report-1",
            project_id="project-1",
            model_revision="model-1",
            design_revision="design-1",
            view_set_id="views-1",
            status=QAStatus.PASS,
            findings=(finding,),
        )


def test_local_repair_requires_valid_region() -> None:
    with pytest.raises(ValidationError, match="requires a normalized region"):
        RepairRequest(
            repair_id="repair-1",
            source_report_id="report-1",
            project_id="project-1",
            design_revision="design-1",
            view_set_id="views-1",
            view_id="view-01",
            finding_ids=("finding-1",),
            strategy=RepairStrategy.LOCAL_INPAINT,
            attempt=1,
        )

    with pytest.raises(ValidationError, match="inside the image"):
        NormalizedRegion(x=0.8, y=0.2, width=0.3, height=0.4)
