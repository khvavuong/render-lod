"""Audit a generated view set for viewpoint and placement, alongside the massing count.

The deterministic edge screen answers "did pixels move under the locked mask", which conflates a
redrawn facade with a rebuilt camera. Freeing the provider to design the facade — the change blind
review showed is worth 4-5 points out of 20 — makes that conflation permanent, so the geometry
question has to be asked another way.

This is the other way: the same vision-judge mechanism the massing gate already uses, asked about
viewpoint, placement and openings. Verdicts are evidence for review, not certification.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from v365_archviz.artifacts import atomic_write
from v365_archviz.domain.workflow import ViewSet
from v365_archviz.errors import InvalidModelError


@dataclass(frozen=True, slots=True)
class ViewAuditReport:
    report_path: Path
    view_count: int
    failed_view_ids: tuple[str, ...]
    review_view_ids: tuple[str, ...]
    unverified_view_ids: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return (
            not self.failed_view_ids and not self.unverified_view_ids and not self.review_view_ids
        )


class VerifyViews:
    """Compare each generated view against the render it was conditioned on."""

    def execute(
        self,
        judge: object,
        render_root: Path,
        generated_root: Path,
        view_set_path: Path,
        output_path: Path | None = None,
    ) -> ViewAuditReport:
        view_set = ViewSet.model_validate_json(view_set_path.read_text(encoding="utf-8"))
        rows: list[dict[str, object]] = []
        failed: list[str] = []
        review: list[str] = []
        unverified: list[str] = []
        for camera in view_set.cameras:
            base = render_root / camera.view_id / "base_rgb.png"
            candidates = sorted((generated_root / camera.view_id).glob("unbranded_refined.*")) or (
                sorted((generated_root / camera.view_id).glob("refined.*"))
            )
            if not base.is_file() or not candidates:
                raise InvalidModelError(f"{camera.view_id} is missing a base or generated image")
            verdict = judge.verify(camera.view_id, base, candidates[0])  # type: ignore[attr-defined]
            rows.append(
                {
                    "view_id": camera.view_id,
                    "role": camera.role.value,
                    "status": verdict.status,
                    "base_sha256": hashlib.sha256(base.read_bytes()).hexdigest(),
                    "image_sha256": hashlib.sha256(candidates[0].read_bytes()).hexdigest(),
                    "viewpoint": verdict.viewpoint,
                    "placement_matches": verdict.placement_matches,
                    "openings_match": verdict.openings_match,
                    "notes": verdict.notes,
                }
            )
            if verdict.status == "fail":
                failed.append(camera.view_id)
            elif verdict.status == "review":
                review.append(camera.view_id)
            elif verdict.status == "unverified":
                unverified.append(camera.view_id)

        document = {
            "schema_version": "1.0.0",
            "view_set_id": view_set.view_set_id,
            "design_revision": view_set.design_revision,
            "note": (
                "Vision-judge evidence for review. A pass is not a geometry certification; an "
                "unverified view is an unanswered question, never an approval."
            ),
            "views": rows,
        }
        report = output_path or generated_root / "view_audit.json"
        atomic_write(report, json.dumps(document, ensure_ascii=False, indent=2).encode() + b"\n")
        return ViewAuditReport(
            report_path=report,
            view_count=len(rows),
            failed_view_ids=tuple(failed),
            review_view_ids=tuple(review),
            unverified_view_ids=tuple(unverified),
        )
