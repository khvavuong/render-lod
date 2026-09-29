"""Hold every view of a studio set to the photographic finish of its approved master."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from v365_archviz.artifacts import atomic_write
from v365_archviz.errors import V365Error
from v365_archviz.providers.gemini_realism_judge import RealismVerdict

logger = logging.getLogger(__name__)

#: Added to the prompt when a view is generated again for falling short of the master.
PARITY_CORRECTION = (
    "REALISM PARITY CORRECTION — the previous attempt at this view was judged against the "
    "approved Design Master and fell short: {notes} Photograph it at the master's level: real "
    "material texture, profiled panel ribs and joints, fixings, weathering and dust, worn "
    "paving, natural vegetation, atmospheric depth and a real lens. Keep the camera, geometry "
    "and design identity unchanged; only the photographic finish improves."
)


class RealismJudge(Protocol):
    def compare(self, view_id: str, candidate: Path, reference: Path) -> RealismVerdict: ...


@dataclass(frozen=True, slots=True)
class ParityResult:
    #: Views that fell short, with the judge's note, in set order.
    failed: dict[str, str]
    report_path: Path


class CheckRealismParity:
    """Judge each view against the master; one paid retry happens only on a clear failure."""

    def execute(
        self,
        judge: RealismJudge,
        view_images: dict[str, Path],
        master: Path,
        report_path: Path,
    ) -> ParityResult:
        verdicts: list[dict[str, object]] = []
        failed: dict[str, str] = {}
        for view_id, image in view_images.items():
            try:
                verdict = judge.compare(view_id, image, master)
            except V365Error:
                # A proofing outage must not fail a set the client already paid for.
                logger.warning("realism proofing of %s failed", view_id, exc_info=True)
                verdicts.append({"view_id": view_id, "status": "unverified", "notes": ""})
                continue
            verdicts.append(
                {
                    "view_id": view_id,
                    "status": verdict.status,
                    "cgi_look": verdict.cgi_look,
                    "less_detailed": verdict.less_detailed,
                    "notes": verdict.notes,
                }
            )
            if verdict.status == "fail":
                failed[view_id] = verdict.notes.strip() or "it looked rendered next to the master."
        atomic_write(
            report_path,
            json.dumps(
                {"schema_version": "1.0.0", "master_image_ref": str(master), "views": verdicts},
                ensure_ascii=False,
                indent=2,
            ).encode("utf-8")
            + b"\n",
        )
        return ParityResult(failed=failed, report_path=report_path)


def record_regeneration(report_path: Path, regenerated: dict[str, str]) -> None:
    """Mark which views were generated again, so the report says what the client received."""

    document = json.loads(report_path.read_text(encoding="utf-8"))
    for item in document.get("views", []):
        if item.get("view_id") in regenerated:
            item["regenerated"] = True
    atomic_write(
        report_path,
        json.dumps(document, ensure_ascii=False, indent=2).encode("utf-8") + b"\n",
    )


def correction_prompt(prompt: str, notes: str) -> str:
    return f"{prompt}\n\n{PARITY_CORRECTION.format(notes=notes)}"
