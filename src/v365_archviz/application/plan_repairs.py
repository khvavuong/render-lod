"""Plan bounded repairs from explicit failed consistency findings."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from v365_archviz.artifacts import atomic_write
from v365_archviz.domain.qa import (
    ConsistencyReport,
    QAStatus,
    RepairRequest,
    RepairStrategy,
)
from v365_archviz.errors import InvalidModelError


@dataclass(frozen=True, slots=True)
class RepairPlanArtifacts:
    plan_path: Path
    requests: tuple[RepairRequest, ...]
    exhausted_view_ids: tuple[str, ...]


class PlanRepairs:
    """Use local repair twice, then one full regeneration, then human review."""

    def execute(
        self,
        report_path: Path,
        attempts_by_view: Mapping[str, int] | None = None,
        output_path: Path | None = None,
    ) -> RepairPlanArtifacts:
        try:
            report = ConsistencyReport.model_validate_json(report_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise InvalidModelError(f"cannot load consistency report: {exc}") from exc

        attempts = dict(attempts_by_view or {})
        for view_id, count in attempts.items():
            if (
                not isinstance(view_id, str)
                or not view_id
                or not isinstance(count, int)
                or isinstance(count, bool)
                or count < 0
            ):
                raise InvalidModelError(
                    "repair attempts must map non-empty view IDs to non-negative integers"
                )
        requests: list[RepairRequest] = []
        exhausted: set[str] = set()
        for finding in report.findings:
            if (
                finding.status is not QAStatus.FAIL
                or not finding.repairable
                or len(finding.view_ids) != 1
            ):
                continue
            view_id = finding.view_ids[0]
            previous_attempts = attempts.get(view_id, 0)
            if previous_attempts >= 3:
                exhausted.add(view_id)
                continue
            attempt = previous_attempts + 1
            strategy = (
                RepairStrategy.LOCAL_INPAINT
                if finding.region is not None and attempt <= 2
                else RepairStrategy.FULL_REGENERATION
            )
            identity = f"{report.report_id}|{view_id}|{finding.finding_id}|{attempt}"
            requests.append(
                RepairRequest(
                    repair_id=f"repair-{hashlib.sha256(identity.encode()).hexdigest()[:16]}",
                    source_report_id=report.report_id,
                    project_id=report.project_id,
                    design_revision=report.design_revision,
                    view_set_id=report.view_set_id,
                    view_id=view_id,
                    finding_ids=(finding.finding_id,),
                    strategy=strategy,
                    attempt=attempt,
                    region=(finding.region if strategy is RepairStrategy.LOCAL_INPAINT else None),
                )
            )

        target = output_path or report_path.with_name("repair_plan.json")
        payload = {
            "schema_version": "1.0.0",
            "source_report_id": report.report_id,
            "requests": [request.model_dump(mode="json") for request in requests],
            "exhausted_view_ids": sorted(exhausted),
            "requires_human_review": bool(exhausted) or not requests,
        }
        atomic_write(
            target,
            json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8") + b"\n",
        )
        return RepairPlanArtifacts(target, tuple(requests), tuple(sorted(exhausted)))
