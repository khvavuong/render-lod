"""Cross-view consistency and bounded repair contracts."""

from __future__ import annotations

from enum import Enum

from pydantic import Field, model_validator

from v365_archviz.domain.common import DomainModel, UnitInterval


class QAGate(str, Enum):
    GEOMETRY = "geometry"
    SEMANTIC = "semantic"
    CROSS_VIEW_APPEARANCE = "cross_view_appearance"
    AESTHETIC = "aesthetic"
    ARTIFACT_INTEGRITY = "artifact_integrity"


class QAStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    REVIEW = "review"


class NormalizedRegion(DomainModel):
    x: UnitInterval
    y: UnitInterval
    width: UnitInterval
    height: UnitInterval

    @model_validator(mode="after")
    def validate_bounds(self) -> NormalizedRegion:
        if self.width <= 0 or self.height <= 0:
            raise ValueError("repair region must have positive area")
        if self.x + self.width > 1 or self.y + self.height > 1:
            raise ValueError("repair region must stay inside the image")
        return self


class QAFinding(DomainModel):
    finding_id: str = Field(min_length=1)
    gate: QAGate
    status: QAStatus
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    view_ids: tuple[str, ...]
    surface_id: str | None = None
    expected: str | int | float | bool | None = None
    actual: str | int | float | bool | None = None
    score: UnitInterval | None = None
    threshold: UnitInterval | None = None
    repairable: bool = False
    region: NormalizedRegion | None = None


class ConsistencyReport(DomainModel):
    report_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    model_revision: str = Field(min_length=1)
    design_revision: str = Field(min_length=1)
    view_set_id: str = Field(min_length=1)
    status: QAStatus
    findings: tuple[QAFinding, ...] = ()

    @model_validator(mode="after")
    def validate_status(self) -> ConsistencyReport:
        has_failure = any(finding.status is QAStatus.FAIL for finding in self.findings)
        has_review = any(finding.status is QAStatus.REVIEW for finding in self.findings)
        expected = (
            QAStatus.FAIL if has_failure else QAStatus.REVIEW if has_review else QAStatus.PASS
        )
        if self.status is not expected:
            raise ValueError(f"report status must be {expected.value} for its finding statuses")
        return self


class RepairStrategy(str, Enum):
    LOCAL_INPAINT = "local_inpaint"
    FULL_REGENERATION = "full_regeneration"


class RepairRequest(DomainModel):
    repair_id: str = Field(min_length=1)
    source_report_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    design_revision: str = Field(min_length=1)
    view_set_id: str = Field(min_length=1)
    view_id: str = Field(min_length=1)
    finding_ids: tuple[str, ...]
    strategy: RepairStrategy
    attempt: int = Field(ge=1, le=3)
    region: NormalizedRegion | None = None
    mask_ref: str | None = None

    @model_validator(mode="after")
    def validate_local_repair(self) -> RepairRequest:
        if not self.finding_ids:
            raise ValueError("repair request must reference at least one finding")
        if self.strategy is RepairStrategy.LOCAL_INPAINT and self.region is None:
            raise ValueError("local inpainting requires a normalized region")
        return self
