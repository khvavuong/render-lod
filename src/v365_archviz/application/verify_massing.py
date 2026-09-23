"""Check every generated view still shows the authored number of building volumes."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from v365_archviz.artifacts import atomic_write
from v365_archviz.domain.design import DesignDNA
from v365_archviz.domain.workflow import ViewSet
from v365_archviz.errors import InvalidModelError
from v365_archviz.providers.gemini_massing_judge import MassingVerdict


@dataclass(frozen=True, slots=True)
class MassingReport:
    report_path: Path
    view_count: int
    failed_view_ids: tuple[str, ...]
    unverified_view_ids: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return not self.failed_view_ids and not self.unverified_view_ids


class VerifyMassing:
    """Compare authored roof-assembly count against what each generated view shows."""

    def execute(
        self,
        judge: object,
        render_root: Path,
        generated_root: Path,
        view_set_path: Path,
        design_dna_path: Path,
        output_path: Path | None = None,
    ) -> MassingReport:
        view_set = ViewSet.model_validate_json(view_set_path.read_text(encoding="utf-8"))
        design = DesignDNA.model_validate_json(design_dna_path.read_text(encoding="utf-8"))
        expected = len(design.roof_assemblies)
        if expected < 1:
            raise InvalidModelError("design has no roof assemblies to verify against")

        verdicts: list[MassingVerdict] = []
        for camera in view_set.cameras:
            base = render_root / camera.view_id / "base_rgb.png"
            candidates = sorted((generated_root / camera.view_id).glob("unbranded_refined.*")) or (
                sorted((generated_root / camera.view_id).glob("refined.*"))
            )
            if not base.is_file() or not candidates:
                raise InvalidModelError(f"{camera.view_id} is missing a base or generated image")
            verdicts.append(
                judge.verify(  # type: ignore[attr-defined]
                    camera.view_id, base, candidates[0], expected
                )
            )

        document = {
            "schema_version": "1.0.0",
            "scope": "generated_view_set",
            "design_revision": design.design_revision,
            "expected_volume_count": expected,
            "status": "pass" if all(v.status == "pass" for v in verdicts) else "fail",
            "note": (
                "Advisory vision-model audit. The deterministic edge screen cannot detect an "
                "invented building volume, so this gate exists to surface that class of error "
                "for human review. It does not certify geometry."
            ),
            "views": [
                {
                    "view_id": v.view_id,
                    "status": v.status,
                    "expected_volume_count": v.expected_volume_count,
                    "base_volume_count": v.base_volume_count,
                    "generated_volume_count": v.generated_volume_count,
                    "notes": v.notes,
                }
                for v in verdicts
            ],
        }
        report_path = output_path or generated_root / "massing_report.json"
        atomic_write(
            report_path,
            json.dumps(document, ensure_ascii=False, indent=2).encode("utf-8") + b"\n",
        )
        return MassingReport(
            report_path=report_path,
            view_count=len(verdicts),
            failed_view_ids=tuple(v.view_id for v in verdicts if v.status == "fail"),
            unverified_view_ids=tuple(v.view_id for v in verdicts if v.status == "unverified"),
        )
