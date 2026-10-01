"""Hold each aerial view to the camera its base render was made with."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from v365_archviz.artifacts import atomic_write
from v365_archviz.errors import V365Error
from v365_archviz.providers.gemini_framing_judge import Box

logger = logging.getLogger(__name__)

#: Mean box overlap below which the camera moved. Measured on 19 labelled concepts: every kept
#: camera scored 0.76 or more, every moved one 0.58 or less.
MIN_OVERLAP = 0.65

#: Added to the prompt when a view is generated again for having moved the camera.
FRAMING_CORRECTION = (
    "CAMERA CORRECTION — the previous attempt at this view moved the camera, so the buildings "
    "no longer stood where Base RGB puts them. Photograph this exact Base RGB frame: the same "
    "viewpoint height, direction and lens, with every building at the same place and size in "
    "the frame. Only the design and the photographic finish may change."
)


class FramingJudge(Protocol):
    def locate(
        self, render: Path, photograph: Path, count: int
    ) -> tuple[tuple[Box, ...], tuple[Box, ...]] | None: ...


def overlap(first: Box, second: Box) -> float:
    """Intersection over union of two [ymin, xmin, ymax, xmax] boxes."""

    height = min(first[2], second[2]) - max(first[0], second[0])
    width = min(first[3], second[3]) - max(first[1], second[1])
    inter = max(0.0, height) * max(0.0, width)

    def area(box: Box) -> float:
        return max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])

    union = area(first) + area(second) - inter
    return inter / union if union > 0 else 0.0


@dataclass(frozen=True, slots=True)
class FramingResult:
    #: Views whose camera moved, in set order.
    failed: tuple[str, ...]
    report_path: Path


class CheckFraming:
    """Compare where the buildings stand in each render and its photograph."""

    def execute(
        self,
        judge: FramingJudge,
        views: dict[str, tuple[Path, Path]],
        building_count: int,
        report_path: Path,
    ) -> FramingResult:
        """`views` maps a view to its (base render, photograph)."""

        verdicts: list[dict[str, object]] = []
        failed: list[str] = []
        for view_id, (render, photograph) in views.items():
            try:
                located = judge.locate(render, photograph, building_count)
            except V365Error:
                # A proofing outage must not fail a set the client already paid for.
                logger.warning("framing proofing of %s failed", view_id, exc_info=True)
                located = None
            if located is None:
                verdicts.append({"view_id": view_id, "status": "unverified"})
                continue
            mean = sum(overlap(a, b) for a, b in zip(*located, strict=True)) / len(located[0])
            status = "pass" if mean >= MIN_OVERLAP else "fail"
            verdicts.append({"view_id": view_id, "status": status, "mean_overlap": mean})
            if status == "fail":
                failed.append(view_id)
        atomic_write(
            report_path,
            json.dumps(
                {"schema_version": "1.0.0", "min_overlap": MIN_OVERLAP, "views": verdicts},
                indent=2,
            ).encode("utf-8")
            + b"\n",
        )
        return FramingResult(failed=tuple(failed), report_path=report_path)


def framing_correction_prompt(prompt: str) -> str:
    return f"{prompt}\n\n{FRAMING_CORRECTION}"
