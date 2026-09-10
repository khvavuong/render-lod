"""Create an explicit, fail-closed certification state for a generated view set."""

from __future__ import annotations

import hashlib
from pathlib import Path

from v365_archviz.artifacts import atomic_write
from v365_archviz.domain.controlled_realism import (
    CertificationEvidence,
    CertificationReport,
    CertificationState,
)
from v365_archviz.domain.qa import ConsistencyReport, QAFinding, QAGate, QAStatus
from v365_archviz.errors import InvalidModelError


class CreateCertificationReport:
    """Translate QA evidence into a state that cannot overclaim deliverable quality."""

    def execute(
        self,
        consistency_report_path: Path,
        technical_report_path: Path,
        protected_composite_manifest_path: Path,
        output_path: Path,
    ) -> CertificationReport:
        try:
            consistency = ConsistencyReport.model_validate_json(
                consistency_report_path.read_text(encoding="utf-8")
            )
        except (OSError, ValueError) as exc:
            raise InvalidModelError(f"cannot load consistency evidence: {exc}") from exc
        for path in (technical_report_path, protected_composite_manifest_path):
            if not path.is_file():
                raise InvalidModelError(f"certification evidence not found: {path}")

        evidence = [
            CertificationEvidence(
                gate=QAGate.ARTIFACT_INTEGRITY,
                status=(
                    QAStatus.FAIL
                    if any(
                        finding.gate is QAGate.ARTIFACT_INTEGRITY
                        and finding.status is QAStatus.FAIL
                        for finding in consistency.findings
                    )
                    else QAStatus.PASS
                ),
                evidence_refs=(str(technical_report_path),),
                message="Technical artifact integrity report is available.",
            )
        ]
        for gate in QAGate:
            if gate is QAGate.ARTIFACT_INTEGRITY:
                continue
            findings = tuple(finding for finding in consistency.findings if finding.gate is gate)
            evidence.append(
                CertificationEvidence(
                    gate=gate,
                    status=self._aggregate(findings),
                    evidence_refs=(
                        str(consistency_report_path),
                        str(protected_composite_manifest_path),
                    ),
                    message=self._message(gate, findings),
                )
            )
        hard_gates = {
            QAGate.ARTIFACT_INTEGRITY,
            QAGate.GEOMETRY,
            QAGate.SEMANTIC,
            QAGate.MATERIAL,
            QAGate.CROSS_VIEW_APPEARANCE,
            QAGate.CAMERA,
        }
        hard_pass = all(
            item.status is QAStatus.PASS for item in evidence if item.gate in hard_gates
        )
        state = (
            CertificationState.GEOMETRY_CERTIFIED
            if hard_pass
            else CertificationState.MARKETING_GENERATIVE_REVIEW
        )
        identity = "|".join(
            (
                consistency.report_id,
                state.value,
                hashlib.sha256(protected_composite_manifest_path.read_bytes()).hexdigest(),
            )
        )
        report = CertificationReport(
            report_id=f"cert-{hashlib.sha256(identity.encode()).hexdigest()[:16]}",
            project_id=consistency.project_id,
            model_revision=consistency.model_revision,
            design_revision=consistency.design_revision,
            view_set_id=consistency.view_set_id,
            state=state,
            evidence=tuple(evidence),
        )
        atomic_write(output_path, report.model_dump_json(indent=2).encode("utf-8") + b"\n")
        return report

    @staticmethod
    def _aggregate(findings: tuple[QAFinding, ...]) -> QAStatus:
        if not findings:
            return QAStatus.REVIEW
        if any(finding.status is QAStatus.FAIL for finding in findings):
            return QAStatus.FAIL
        if any(finding.status is QAStatus.REVIEW for finding in findings):
            return QAStatus.REVIEW
        return QAStatus.PASS

    @staticmethod
    def _message(gate: QAGate, findings: tuple[QAFinding, ...]) -> str:
        if not findings:
            return f"No measured evidence is available for {gate.value}."
        return " ".join(dict.fromkeys(finding.message for finding in findings))
