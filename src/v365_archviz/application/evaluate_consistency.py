"""Build a fail-closed consistency report from available QA evidence."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from v365_archviz.artifacts import atomic_write
from v365_archviz.domain.qa import ConsistencyReport, QAFinding, QAGate, QAStatus
from v365_archviz.errors import InvalidModelError


@dataclass(frozen=True, slots=True)
class ConsistencyArtifacts:
    report_path: Path
    report: ConsistencyReport


class EvaluateConsistency:
    """Combine deterministic checks without overstating visual conformance."""

    def execute(
        self,
        technical_report_path: Path,
        model_revision: str,
        view_set_id: str,
        output_path: Path | None = None,
    ) -> ConsistencyArtifacts:
        try:
            technical = json.loads(technical_report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise InvalidModelError(f"cannot load technical QA report: {exc}") from exc

        project_id = self._required_string(technical, "project_id")
        design_revision = self._required_string(technical, "design_revision")
        findings = self._technical_findings(technical)
        if not findings:
            findings.extend(self._unresolved_visual_gates(technical))

        status = (
            QAStatus.FAIL
            if any(item.status is QAStatus.FAIL for item in findings)
            else QAStatus.REVIEW
            if any(item.status is QAStatus.REVIEW for item in findings)
            else QAStatus.PASS
        )
        identity = "|".join(
            (
                project_id,
                model_revision,
                design_revision,
                view_set_id,
                *(finding.finding_id for finding in findings),
            )
        )
        report = ConsistencyReport(
            report_id=f"consistency-{hashlib.sha256(identity.encode()).hexdigest()[:16]}",
            project_id=project_id,
            model_revision=model_revision,
            design_revision=design_revision,
            view_set_id=view_set_id,
            status=status,
            findings=tuple(findings),
        )
        target = output_path or technical_report_path.with_name("consistency_report.json")
        atomic_write(
            target,
            report.model_dump_json(indent=2).encode("utf-8") + b"\n",
        )
        return ConsistencyArtifacts(target, report)

    @staticmethod
    def _required_string(document: dict[str, Any], field: str) -> str:
        value = document.get(field)
        if not isinstance(value, str) or not value:
            raise InvalidModelError(f"technical QA report is missing {field}")
        return value

    @staticmethod
    def _technical_findings(document: dict[str, Any]) -> list[QAFinding]:
        findings: list[QAFinding] = []
        raw_findings: list[tuple[str, dict[str, Any]]] = []
        for view in document.get("views", []):
            if not isinstance(view, dict):
                continue
            view_id = str(view.get("view_id", "unknown-view"))
            raw_findings.extend(
                (view_id, finding)
                for finding in view.get("findings", [])
                if isinstance(finding, dict) and finding.get("severity") == "error"
            )
        raw_findings.extend(
            ("view-set", finding)
            for finding in document.get("global_findings", [])
            if isinstance(finding, dict) and finding.get("severity") == "error"
        )
        for index, (view_id, finding) in enumerate(raw_findings, start=1):
            code = str(finding.get("code", "unknown_integrity_error"))
            findings.append(
                QAFinding(
                    finding_id=f"artifact-{index:03d}-{code}",
                    gate=QAGate.ARTIFACT_INTEGRITY,
                    status=QAStatus.FAIL,
                    code=code,
                    message=str(finding.get("message", code)),
                    view_ids=() if view_id == "view-set" else (view_id,),
                    repairable=False,
                )
            )
        return findings

    @staticmethod
    def _unresolved_visual_gates(document: dict[str, Any]) -> list[QAFinding]:
        view_ids = tuple(
            str(view["view_id"])
            for view in document.get("views", [])
            if isinstance(view, dict) and view.get("view_id")
        )
        messages = {
            QAGate.GEOMETRY: "Silhouette and structural edge conformance require review.",
            QAGate.SEMANTIC: "Architectural element presence and role require review.",
            QAGate.CROSS_VIEW_APPEARANCE: (
                "Material, color, and identity consistency across views require review."
            ),
            QAGate.AESTHETIC: "Bid-quality composition and visual appeal require review.",
        }
        return [
            QAFinding(
                finding_id=f"review-{gate.value}",
                gate=gate,
                status=QAStatus.REVIEW,
                code="evidence_not_available",
                message=message,
                view_ids=view_ids,
                repairable=False,
            )
            for gate, message in messages.items()
        ]
