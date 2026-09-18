"""Re-plan the views a conditioning gate rejected, instead of shipping them or failing the import.

An upload has to produce usable angles without anyone hunting for them, so the planner answers
analytically and instantly. What it cannot know before rendering is whether a camera it derived is
actually obstructed on this site: that only shows up once the conditioning render exists, and the
gate already measures it.

This closes the loop. A rejected slot is re-derived from a different side, and only that view is
rendered again — the rest of the set is untouched, so the repair costs one render rather than a
search. The offsets are tried in a fixed order so the same import always repairs the same way.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from v365_archviz.domain.workflow import Camera, ViewSet

#: Orbit steps tried in order when a slot is rejected. Small first, because the derived bearing is
#: evidence about where the site is entered and moving far from it is a worse answer than moving a
#: little; alternating sides so a second attempt does not repeat the first one's obstruction.
REPAIR_BEARING_OFFSETS_DEG: tuple[float, ...] = (35.0, -35.0, 70.0, -70.0, 110.0)


@dataclass(frozen=True, slots=True)
class RepairPlan:
    """Which views need re-rendering, and the cameras to render them with."""

    attempt: int
    bearing_offset_deg: float
    view_set: ViewSet
    repaired_view_ids: tuple[str, ...]

    @property
    def exhausted(self) -> bool:
        return not self.repaired_view_ids


def failed_view_ids(conditioning_report: Path) -> tuple[str, ...]:
    """View ids the gate rejected. A missing report is not an approval."""

    if not conditioning_report.is_file():
        raise FileNotFoundError(f"conditioning report does not exist: {conditioning_report}")
    document = json.loads(conditioning_report.read_text(encoding="utf-8"))
    views = document.get("views")
    if not isinstance(views, list):
        raise ValueError(f"conditioning report has no view list: {conditioning_report}")
    return tuple(
        str(view["view_id"])
        for view in views
        if isinstance(view, dict) and view.get("status") == "fail"
    )


def merge_repaired_views(
    current: ViewSet,
    replanned: ViewSet,
    repaired_view_ids: tuple[str, ...],
) -> ViewSet:
    """Take the re-derived cameras for the rejected slots and keep every other camera as it was.

    Replacing the whole set would move views the gate already accepted, which costs five renders
    to fix one and breaks any approval already given against them.
    """

    replacements = {camera.view_id: camera for camera in replanned.cameras}
    merged: list[Camera] = []
    for camera in current.cameras:
        if camera.view_id in repaired_view_ids and camera.view_id in replacements:
            merged.append(replacements[camera.view_id])
        else:
            merged.append(camera)
    return ViewSet(
        view_set_id=current.view_set_id,
        design_revision=current.design_revision,
        cameras=tuple(merged),
    )
