"""Versioned user-facing render intent and server-owned option catalog."""

from __future__ import annotations

from enum import Enum

from pydantic import Field

from v365_archviz.domain.common import DomainModel
from v365_archviz.domain.design import DecorLevel, MaterialPalette, StylePreset


class CreativeBudget(str, Enum):
    STRICT = "strict"
    BALANCED = "balanced"
    EXPLORATORY = "exploratory"


class LoadingDockPolicy(str, Enum):
    PRESERVE_EXISTING = "preserve_existing"
    SUGGEST_IF_MISSING = "suggest_if_missing"
    EXACT_ON_ELIGIBLE_FACADE = "exact_on_eligible_facade"


class LandscapePreset(str, Enum):
    TROPICAL_RESTRAINED = "tropical_restrained"
    CORPORATE_LINEAR = "corporate_linear"
    LOW_MAINTENANCE = "low_maintenance"


class ContextPresentation(str, Enum):
    AUTHORED_ONLY = "authored_only"
    NEUTRAL_INDUSTRIAL_MASSING = "neutral_industrial_massing"


class RealismPreset(str, Enum):
    DOCUMENTARY_ARCHITECTURAL_PHOTO = "documentary_architectural_photo"
    PREMIUM_BID_PHOTO = "premium_bid_photo"


class EntourageDensity(str, Enum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class UserRenderIntent(DomainModel):
    """Safe public contract; it contains intent, never authoritative geometry."""

    schema_version: str = Field(default="1.0.0", pattern=r"^1\.0\.0$")
    style_preset: StylePreset = StylePreset.CONTEMPORARY_INDUSTRIAL
    creative_budget: CreativeBudget = CreativeBudget.BALANCED
    material_palette: MaterialPalette = Field(default_factory=MaterialPalette)
    decor_level: DecorLevel = DecorLevel.BALANCED
    office_facade_rhythm: int = Field(default=2, ge=1, le=8)
    loading_dock_policy: LoadingDockPolicy = LoadingDockPolicy.SUGGEST_IF_MISSING
    loading_dock_count: int = Field(default=3, ge=0, le=12)
    landscape_preset: LandscapePreset = LandscapePreset.TROPICAL_RESTRAINED
    entourage_density: EntourageDensity = EntourageDensity.LOW
    time: str = Field(default="09:30", pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    context_presentation: ContextPresentation = ContextPresentation.AUTHORED_ONLY
    realism_preset: RealismPreset = RealismPreset.DOCUMENTARY_ARCHITECTURAL_PHOTO
    free_text: str | None = Field(default=None, max_length=1000)


class IntentWarning(DomainModel):
    code: str = Field(min_length=1)
    field: str = Field(min_length=1)
    message: str = Field(min_length=1)
    ignored_text: str | None = None


class DesignOption(DomainModel):
    value: str = Field(min_length=1)
    label: str = Field(min_length=1)
    description: str = Field(min_length=1)


class DesignOptionsCatalog(DomainModel):
    schema_version: str = "1.0.0"
    catalog_version: str = "industrial-intent-v1"
    styles: tuple[DesignOption, ...]
    decor_levels: tuple[DesignOption, ...]
    landscapes: tuple[DesignOption, ...]
    creative_budgets: tuple[DesignOption, ...]
    loading_dock_policies: tuple[DesignOption, ...]
    context_presentations: tuple[DesignOption, ...]
    realism_presets: tuple[DesignOption, ...]


DESIGN_OPTIONS = DesignOptionsCatalog(
    styles=(
        DesignOption(
            value=StylePreset.CONTEMPORARY_INDUSTRIAL.value,
            label="Công nghiệp đương đại",
            description="Tỷ lệ thực dụng, facade hiện đại và phù hợp nhà xưởng Việt Nam.",
        ),
        DesignOption(
            value=StylePreset.MINIMAL_INDUSTRIAL.value,
            label="Tối giản tinh tế",
            description="Nhịp facade kỷ luật, ít chi tiết và vật liệu trung tính.",
        ),
        DesignOption(
            value=StylePreset.CORPORATE_INDUSTRIAL.value,
            label="Nhận diện doanh nghiệp",
            description="Lối vào rõ ràng và điểm nhấn thương hiệu có kiểm soát.",
        ),
        DesignOption(
            value=StylePreset.SUSTAINABLE_INDUSTRIAL.value,
            label="Công nghiệp xanh",
            description="Bao che thích ứng khí hậu và cảnh quan tiết chế.",
        ),
        DesignOption(
            value=StylePreset.REFINED_HIGH_TECH.value,
            label="High-tech tiết chế",
            description="Chi tiết kỹ thuật chính xác nhưng vẫn khả thi xây dựng.",
        ),
    ),
    decor_levels=(
        DesignOption(value="minimal", label="Tối giản", description="Hầu như không tạo điểm nhấn."),
        DesignOption(value="subtle", label="Nhẹ", description="Một số chi tiết facade nhỏ."),
        DesignOption(value="balanced", label="Cân bằng", description="Đủ nhận diện và thực dụng."),
        DesignOption(
            value="expressive", label="Nổi bật", description="Điểm nhấn mạnh hơn trong envelope."
        ),
    ),
    landscapes=(
        DesignOption(
            value="tropical_restrained",
            label="Nhiệt đới tiết chế",
            description="Cây phù hợp khí hậu, tập trung tại lối vào và dải xanh authored.",
        ),
        DesignOption(
            value="corporate_linear",
            label="Tuyến tính doanh nghiệp",
            description="Hàng cây và bụi thấp có nhịp rõ ràng.",
        ),
        DesignOption(
            value="low_maintenance",
            label="Ít bảo trì",
            description="Cây chịu hạn và bề mặt xanh đơn giản.",
        ),
    ),
    creative_budgets=(
        DesignOption(value="strict", label="Chặt chẽ", description="Ưu tiên bám model tối đa."),
        DesignOption(
            value="balanced", label="Cân bằng", description="Cho phép làm đẹp có kiểm soát."
        ),
        DesignOption(
            value="exploratory", label="Khám phá", description="Tăng biến thể ở vùng được phép."
        ),
    ),
    loading_dock_policies=(
        DesignOption(
            value="preserve_existing",
            label="Giữ theo model",
            description="Không đề xuất thêm cửa xuất nhập hàng.",
        ),
        DesignOption(
            value="suggest_if_missing",
            label="Đề xuất khi thiếu",
            description="Chỉ đặt trên facade nhà xưởng đủ điều kiện.",
        ),
        DesignOption(
            value="exact_on_eligible_facade",
            label="Đúng số lượng",
            description="Đặt đúng số yêu cầu trên một facade đủ điều kiện.",
        ),
    ),
    context_presentations=(
        DesignOption(
            value="authored_only",
            label="Chỉ theo model",
            description="Không phát sinh thêm khối bối cảnh ngoài dữ liệu.",
        ),
        DesignOption(
            value="neutral_industrial_massing",
            label="Khối công nghiệp trung tính",
            description="Làm dịu các footprint context đã có chứng cứ.",
        ),
    ),
    realism_presets=(
        DesignOption(
            value="documentary_architectural_photo",
            label="Ảnh kiến trúc chân thật",
            description="Ánh sáng, vật liệu và ống kính gần ảnh chụp hiện trường.",
        ),
        DesignOption(
            value="premium_bid_photo",
            label="Ảnh hồ sơ thầu cao cấp",
            description="Hoàn thiện sạch hơn nhưng vẫn giữ tính thực tế.",
        ),
    ),
)
