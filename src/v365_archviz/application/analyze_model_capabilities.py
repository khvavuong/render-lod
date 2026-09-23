"""Derive user-configurable design capabilities from canonical scene evidence."""

from __future__ import annotations

from collections.abc import Iterable

from v365_archviz.domain.render_intent import ComponentCapability, ModelDesignCapabilities
from v365_archviz.domain.scene import CanonicalScene, SemanticRole


class AnalyzeModelDesignCapabilities:
    """Expose only controls that can be grounded in model geometry/semantics."""

    def execute(self, model_revision: str, scene: CanonicalScene) -> ModelDesignCapabilities:
        by_role = {
            role: tuple(
                element.scene_element_id
                for element in scene.elements
                if element.semantic_role is role
            )
            for role in SemanticRole
        }
        facade_ids = tuple(
            surface.surface_id
            for surface in scene.surfaces
            if surface.semantic_role is SemanticRole.PRIMARY_FACADE
        )

        components = (
            self._component(
                "envelope",
                "Bao che nhà xưởng",
                (*by_role[SemanticRole.MAIN_SHED], *facade_ids),
                "Có khối xưởng hoặc mặt đứng chính để áp dụng hệ bao che.",
                "Chưa nhận diện được khối xưởng/mặt đứng chính.",
            ),
            self._component(
                "office_entrance",
                "Khối văn phòng và lối vào",
                by_role[SemanticRole.OFFICE_BLOCK],
                "Có khối văn phòng authored để áp dụng ngôn ngữ lối vào.",
                "Không có chứng cứ khối văn phòng; hệ thống sẽ không gắn sảnh giả lên nhà xưởng.",
            ),
            self._component(
                "logistics",
                "Khu logistics",
                (
                    *by_role[SemanticRole.LOADING_ZONE],
                    *by_role[SemanticRole.SERVICE_YARD],
                    *by_role[SemanticRole.LOADING_DOCK],
                ),
                "Có loading zone hoặc service yard authored.",
                "Không có vùng logistics authored; không được tự thêm cửa dock.",
            ),
            self._component(
                "boundary",
                "Hàng rào",
                by_role[SemanticRole.SITE_BOUNDARY],
                "Có ranh giới/hàng rào authored.",
                "Chưa nhận diện được hàng rào; không được phát sinh ranh mới.",
            ),
            self._component(
                "gate",
                "Cổng",
                (*by_role[SemanticRole.MAIN_ENTRANCE], *by_role[SemanticRole.SECONDARY_ENTRANCE]),
                "Có opening cổng authored để hoàn thiện.",
                "Chưa nhận diện được opening cổng; không được đặt cổng giả.",
            ),
            self._component(
                "landscape",
                "Cảnh quan",
                by_role[SemanticRole.LANDSCAPE_ZONE],
                "Có vùng cảnh quan authored.",
                "Không có vùng xanh authored; chỉ giữ bối cảnh model.",
            ),
            self._component(
                "circulation",
                "Giao thông nội bộ",
                (
                    *by_role[SemanticRole.SITE_ROAD],
                    *by_role[SemanticRole.SIDEWALK],
                    *by_role[SemanticRole.PARKING],
                ),
                "Có đường, vỉa hè hoặc bãi xe authored.",
                "Chưa nhận diện được giao thông nội bộ; view tổng thể cần kiểm tra thủ công.",
            ),
            self._component(
                "roof_finish",
                "Hoàn thiện mái",
                (*by_role[SemanticRole.ROOF], *by_role[SemanticRole.MAIN_SHED]),
                "Có mái hoặc khối xưởng để áp dụng vật liệu mái; hình học mái vẫn bị khóa.",
                "Chưa nhận diện được mái/khối xưởng.",
            ),
        )
        warnings = tuple(component.reason for component in components if not component.supported)
        return ModelDesignCapabilities(
            model_revision=model_revision,
            components=components,
            warnings=warnings,
        )

    @staticmethod
    def _component(
        key: str,
        label: str,
        evidence: Iterable[str],
        supported_reason: str,
        unsupported_reason: str,
    ) -> ComponentCapability:
        evidence_ids = tuple(dict.fromkeys(evidence))
        return ComponentCapability(
            key=key,
            label=label,
            supported=bool(evidence_ids),
            evidence_count=len(evidence_ids),
            evidence_ids=evidence_ids,
            reason=supported_reason if evidence_ids else unsupported_reason,
        )
