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
            f"{scene.source.version_id}\n{design_revision}\nindustrial-context-v1".encode()
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
        setback = max(24.0, scale * 0.16)
        road_offset = setback * 1.15
        ground_extent = scale * 4.5
        ground = BoundingBox(
            minimum=(cx - ground_extent / 2, cy - ground_extent / 2, z0 - 0.4),
            maximum=(cx + ground_extent / 2, cy + ground_extent / 2, z0 - 0.2),
        )
        road_length_x = span_x + setback * 7
        road_length_y = span_y + setback * 7
        roads = (
            self._road("context-road-north", cx, y1 + road_offset, z0, road_length_x, road_width),
            self._road("context-road-south", cx, y0 - road_offset, z0, road_length_x, road_width),
            self._road("context-road-east", x1 + road_offset, cy, z0, road_width, road_length_y),
            self._road("context-road-west", x0 - road_offset, cy, z0, road_width, road_length_y),
        )
        long_size = max(45.0, min(110.0, scale * 0.34))
        short_size = max(22.0, min(50.0, min(span_x, span_y) * 0.30))
        height = max(7.0, min(13.0, (z1 - z0) * 0.82))
        far = road_offset + road_width / 2 + short_size / 2 + setback * 0.45
        slots = (
            (cx - span_x * 0.28, y1 + far, long_size, short_size),
            (cx + span_x * 0.28, y1 + far, long_size, short_size),
            (cx - span_x * 0.28, y0 - far, long_size, short_size),
            (cx + span_x * 0.28, y0 - far, long_size, short_size),
            (x1 + far, cy, short_size, long_size),
            (x0 - far, cy, short_size, long_size),
        )
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
