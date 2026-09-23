"""Plan stable conceptual industrial-estate context around an authored project site."""

from __future__ import annotations

import hashlib

from v365_archviz.domain.design import (
    ContextProxyBuilding,
    ContextRoad,
    IndustrialContextPlan,
    SiteDesign,
)
from v365_archviz.domain.scene import BoundingBox, CanonicalScene, SemanticRole


def _union(boxes: list[BoundingBox]) -> BoundingBox:
    return BoundingBox(
        minimum=(
            min(box.minimum[0] for box in boxes),
            min(box.minimum[1] for box in boxes),
            min(box.minimum[2] for box in boxes),
        ),
        maximum=(
            max(box.maximum[0] for box in boxes),
            max(box.maximum[1] for box in boxes),
            max(box.maximum[2] for box in boxes),
        ),
    )


class PlanIndustrialContext:
    """Create model-relative roads and proxy sheds without sample-specific coordinates."""

    def execute(
        self,
        scene: CanonicalScene,
        design_revision: str,
        site: SiteDesign,
    ) -> IndustrialContextPlan:
        mode = site.surrounding_context_mode
        seed = hashlib.sha256(
            f"{scene.source.version_id}\n{design_revision}\nindustrial-context-v2".encode()
        ).hexdigest()[:16]
        if mode in {"authored_only", "none"}:
            return IndustrialContextPlan(mode=mode, seed=seed)

        boundary_boxes = [
            item.bounding_box
            for item in scene.elements
            if item.semantic_role is SemanticRole.SITE_BOUNDARY
        ]
        project_boxes = [
            item.bounding_box
            for item in scene.elements
            if item.semantic_role
            in {
                SemanticRole.MAIN_SHED,
                SemanticRole.OFFICE_BLOCK,
                SemanticRole.UTILITY_BLOCK,
                SemanticRole.SITE_ROAD,
                SemanticRole.SIDEWALK,
                SemanticRole.PARKING,
                SemanticRole.LOADING_ZONE,
                SemanticRole.SERVICE_YARD,
                SemanticRole.LANDSCAPE_ZONE,
                SemanticRole.MAIN_ENTRANCE,
                SemanticRole.SECONDARY_ENTRANCE,
            }
        ]
        boxes = boundary_boxes or project_boxes or [item.bounding_box for item in scene.elements]
        site_box = _union(boxes)
        x0, y0, z0 = site_box.minimum
        x1, y1, z1 = site_box.maximum
        span_x = max(20.0, x1 - x0)
        span_y = max(20.0, y1 - y0)
        scale = max(span_x, span_y)
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        road_width = max(9.0, min(16.0, min(span_x, span_y) * 0.06))
        setback = max(24.0, scale * 0.14)
        road_offset = setback + road_width / 2
        ground_extent = scale * 3.0
        ground = BoundingBox(
            minimum=(cx - ground_extent / 2, cy - ground_extent / 2, z0 - 0.4),
            maximum=(cx + ground_extent / 2, cy + ground_extent / 2, z0 - 0.2),
        )
        entrance_boxes = [
            item.bounding_box
            for item in scene.elements
            if item.semantic_role in {SemanticRole.MAIN_ENTRANCE, SemanticRole.SECONDARY_ENTRANCE}
        ]
        entrance_sides: list[tuple[str, BoundingBox]] = []
        for box in entrance_boxes:
            gate_x = (box.minimum[0] + box.maximum[0]) / 2
            gate_y = (box.minimum[1] + box.maximum[1]) / 2
            side = min(
                (
                    (abs(gate_x - x0), "west"),
                    (abs(gate_x - x1), "east"),
                    (abs(gate_y - y0), "south"),
                    (abs(gate_y - y1), "north"),
                )
            )[1]
            entrance_sides.append((side, box))

        # Derive estate roads from authored gate sides. Four unrelated perimeter bars made the
        # project read as an isolated parcel and could not explain how a truck reaches a gate.
        active_sides = list(dict.fromkeys(side for side, _box in entrance_sides))
        if not active_sides:
            active_sides = ["west", "east"] if span_x >= span_y else ["south", "north"]
        road_length_x = span_x + setback * 4
        road_length_y = span_y + setback * 4
        estate_roads: list[ContextRoad] = []
        for side in active_sides:
            if side == "north":
                estate_roads.append(
                    self._road(
                        "context-road-north", cx, y1 + road_offset, z0, road_length_x, road_width
                    )
                )
            elif side == "south":
                estate_roads.append(
                    self._road(
                        "context-road-south", cx, y0 - road_offset, z0, road_length_x, road_width
                    )
                )
            elif side == "east":
                estate_roads.append(
                    self._road(
                        "context-road-east", x1 + road_offset, cy, z0, road_width, road_length_y
                    )
                )
            else:
                estate_roads.append(
                    self._road(
                        "context-road-west", x0 - road_offset, cy, z0, road_width, road_length_y
                    )
                )

        # Join every authored gate to the nearest estate road while leaving the model-derived
        # internal driveway and gate geometry untouched.
        approach_roads: list[ContextRoad] = []
        for index, (side, box) in enumerate(entrance_sides, start=1):
            gate_x = (box.minimum[0] + box.maximum[0]) / 2
            gate_y = (box.minimum[1] + box.maximum[1]) / 2
            gate_width = max(
                road_width * 0.72,
                (box.maximum[1] - box.minimum[1])
                if side in {"west", "east"}
                else (box.maximum[0] - box.minimum[0]),
            )
            if side == "west":
                approach_roads.append(
                    self._road(
                        f"context-approach-{index:02d}",
                        x0 - road_offset / 2,
                        gate_y,
                        z0 + 0.01,
                        road_offset,
                        gate_width,
                    )
                )
            elif side == "east":
                approach_roads.append(
                    self._road(
                        f"context-approach-{index:02d}",
                        x1 + road_offset / 2,
                        gate_y,
                        z0 + 0.01,
                        road_offset,
                        gate_width,
                    )
                )
            elif side == "south":
                approach_roads.append(
                    self._road(
                        f"context-approach-{index:02d}",
                        gate_x,
                        y0 - road_offset / 2,
                        z0 + 0.01,
                        gate_width,
                        road_offset,
                    )
                )
            else:
                approach_roads.append(
                    self._road(
                        f"context-approach-{index:02d}",
                        gate_x,
                        y1 + road_offset / 2,
                        z0 + 0.01,
                        gate_width,
                        road_offset,
                    )
                )
        roads = tuple((*estate_roads, *approach_roads))
        long_size = max(45.0, min(110.0, scale * 0.34))
        short_size = max(22.0, min(50.0, min(span_x, span_y) * 0.30))
        height = max(7.0, min(13.0, (z1 - z0) * 0.82))
        # Hold the neighbours well clear of the project. A near ring crowds the frame and makes
        # the project read as one shed among equals; pushing the first row out by a fraction of
        # the site's own scale keeps it the dominant mass and leaves its yards legible.
        prominence_standoff = max(40.0, scale * 0.14)
        far = (
            road_offset
            + road_width / 2
            + short_size / 2
            + setback * 0.42
            + prominence_standoff
        )
        # Neighbouring lots occupy two rows on every active side. A single ring at one standoff
        # reads from the air as isolated blocks floating in empty land; a second row behind the
        # first, staggered along the frontage, reads as the project holding one lot inside an
        # estate that continues past it.
        row_depth = short_size + road_width + setback * 0.5
        rows = (far, far + row_depth)
        spacing = max(long_size * 1.25, scale * 0.30)
        slots: list[tuple[float, float, float, float]] = []
        per_side = max(
            1,
            (site.surrounding_context_count + len(active_sides) * len(rows) - 1)
            // (len(active_sides) * len(rows)),
        )
        for row_index, distance in enumerate(rows):
            stagger = spacing * 0.5 * row_index
            for side in active_sides:
                for slot_index in range(per_side):
                    offset = (slot_index - (per_side - 1) / 2) * spacing + stagger
                    if side == "north":
                        slots.append((cx + offset, y1 + distance, long_size, short_size))
                    elif side == "south":
                        slots.append((cx + offset, y0 - distance, long_size, short_size))
                    elif side == "east":
                        slots.append((x1 + distance, cy + offset, short_size, long_size))
                    else:
                        slots.append((x0 - distance, cy + offset, short_size, long_size))
        proxies = tuple(
            ContextProxyBuilding(
                proxy_id=f"context-proxy-{index:02d}",
                bounding_box=BoundingBox(
                    minimum=(px - width / 2, py - depth / 2, z0),
                    maximum=(px + width / 2, py + depth / 2, z0 + height),
                ),
                opacity=site.context_opacity,
            )
            for index, (px, py, width, depth) in enumerate(
                slots[: site.surrounding_context_count], start=1
            )
        )
        return IndustrialContextPlan(
            mode="conceptual_industrial_park",
            seed=seed,
            ground=ground,
            roads=roads,
            proxy_buildings=proxies,
        )

    @staticmethod
    def _road(
        road_id: str,
        center_x: float,
        center_y: float,
        elevation: float,
        width: float,
        depth: float,
    ) -> ContextRoad:
        return ContextRoad(
            road_id=road_id,
            bounding_box=BoundingBox(
                minimum=(center_x - width / 2, center_y - depth / 2, elevation - 0.12),
                maximum=(center_x + width / 2, center_y + depth / 2, elevation),
            ),
        )
