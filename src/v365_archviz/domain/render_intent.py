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


class DesignPackage(str, Enum):
    PREMIUM_PRACTICAL = "premium_practical"
    CORPORATE_IDENTITY = "corporate_identity"
    TROPICAL_INDUSTRIAL = "tropical_industrial"
    MINIMAL_LOGISTICS = "minimal_logistics"


class EnvelopeKit(str, Enum):
    PROFILED_METAL_VERTICAL = "profiled_metal_vertical"
    SANDWICH_PANEL_FLAT = "sandwich_panel_flat"
    PANEL_CONCRETE_PLINTH = "panel_concrete_plinth"


class OfficeEntranceKit(str, Enum):
    PRESERVE_MODEL = "preserve_model"
    FRAMED_GLAZED_BAY = "framed_glazed_bay"
    CANOPY_ENTRY = "canopy_entry"
    CLIMATE_SCREEN = "climate_screen"


class FacadeRhythmKit(str, Enum):
    HORIZONTAL_RESTRAINED = "horizontal_restrained"
    VERTICAL_BAYS = "vertical_bays"
    MIXED_RESTRAINED = "mixed_restrained"


class LogisticsKit(str, Enum):
    PRESERVE_MODEL = "preserve_model"
    AUTHORED_DOCK_FINISH = "authored_dock_finish"


class BoundaryKit(str, Enum):
    PRESERVE_MODEL = "preserve_model"
    MESH_LOW_PLINTH = "mesh_low_plinth"
    VERTICAL_BAR = "vertical_bar"


class GateKit(str, Enum):
    PRESERVE_MODEL = "preserve_model"
    INDUSTRIAL_SLIDING = "industrial_sliding"
    HINGED = "hinged"


class OperatingScene(str, Enum):
    CLEAN = "clean"
    ACTIVE = "active"
    LOGISTICS = "logistics"


class DeliveryQuality(str, Enum):
    PREVIEW = "preview"
    MARKETING = "marketing"
    TENDER = "tender"


class LoadingDockPolicy(str, Enum):
    PRESERVE_EXISTING = "preserve_existing"
    SUGGEST_IF_MISSING = "suggest_if_missing"
    EXACT_ON_ELIGIBLE_FACADE = "exact_on_eligible_facade"


class LandscapePreset(str, Enum):
    PRESERVE_MODEL = "preserve_model"
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
    design_package: DesignPackage = DesignPackage.PREMIUM_PRACTICAL
    envelope_kit: EnvelopeKit = EnvelopeKit.PROFILED_METAL_VERTICAL
    office_entrance_kit: OfficeEntranceKit = OfficeEntranceKit.PRESERVE_MODEL
    facade_rhythm_kit: FacadeRhythmKit = FacadeRhythmKit.MIXED_RESTRAINED
    logistics_kit: LogisticsKit = LogisticsKit.PRESERVE_MODEL
    boundary_kit: BoundaryKit = BoundaryKit.PRESERVE_MODEL
    gate_kit: GateKit = GateKit.PRESERVE_MODEL
    accent_coverage_percent: int = Field(default=5, ge=3, le=8)
    operating_scene: OperatingScene = OperatingScene.ACTIVE
    delivery_quality: DeliveryQuality = DeliveryQuality.TENDER
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
    requires_capability: str | None = None


class ComponentCapability(DomainModel):
    key: str = Field(min_length=1)
    label: str = Field(min_length=1)
    supported: bool
    evidence_count: int = Field(ge=0)
    evidence_ids: tuple[str, ...] = ()
    reason: str = Field(min_length=1)


class ModelDesignCapabilities(DomainModel):
    schema_version: str = "1.0.0"
    model_revision: str = Field(min_length=1)
    components: tuple[ComponentCapability, ...]
    warnings: tuple[str, ...] = ()


class DesignOptionsCatalog(DomainModel):
    schema_version: str = "1.0.0"
    catalog_version: str = "industrial-intent-v1"
    design_packages: tuple[DesignOption, ...] = ()
    envelope_kits: tuple[DesignOption, ...] = ()
    office_entrance_kits: tuple[DesignOption, ...] = ()
    facade_rhythm_kits: tuple[DesignOption, ...] = ()
    logistics_kits: tuple[DesignOption, ...] = ()
    boundary_kits: tuple[DesignOption, ...] = ()
    gate_kits: tuple[DesignOption, ...] = ()
    operating_scenes: tuple[DesignOption, ...] = ()
    delivery_qualities: tuple[DesignOption, ...] = ()
    styles: tuple[DesignOption, ...]
    decor_levels: tuple[DesignOption, ...]
    landscapes: tuple[DesignOption, ...]
    creative_budgets: tuple[DesignOption, ...]
    loading_dock_policies: tuple[DesignOption, ...]
    context_presentations: tuple[DesignOption, ...]
    realism_presets: tuple[DesignOption, ...]


DESIGN_OPTIONS = DesignOptionsCatalog(
    catalog_version="industrial-intent-v2",
    design_packages=(
        DesignOption(
            value="premium_practical",
            label="Thực dụng cao cấp",
            description="Cân bằng hình ảnh hồ sơ thầu, chi tiết thi công và nhận diện tiết chế.",
        ),
        DesignOption(
            value="corporate_identity",
            label="Nhận diện doanh nghiệp",
            description="Nhấn có kiểm soát tại khối văn phòng và điểm đến chính.",
        ),
        DesignOption(
            value="tropical_industrial",
            label="Công nghiệp nhiệt đới",
            description="Bao che thích ứng khí hậu và cảnh quan phù hợp Việt Nam.",
        ),
        DesignOption(
            value="minimal_logistics",
            label="Logistics tối giản",
            description="Ưu tiên vận hành, nhịp facade rõ và vật liệu bền vững.",
        ),
    ),
    envelope_kits=(
        DesignOption(
            value="profiled_metal_vertical",
            label="Tôn đứng công nghiệp",
            description="Tôn định hình đứng, diềm và chân tường có tỷ lệ thực tế.",
        ),
        DesignOption(
            value="sandwich_panel_flat",
            label="Panel phẳng",
            description="Panel cách nhiệt phẳng với joint module kỷ luật.",
        ),
        DesignOption(
            value="panel_concrete_plinth",
            label="Panel + chân bê tông",
            description="Bao che nhẹ phía trên và chân tường chịu va đập.",
        ),
    ),
    office_entrance_kits=(
        DesignOption(
            value="preserve_model",
            label="Giữ theo model",
            description="Không phát sinh cấu kiện lối vào mới.",
        ),
        DesignOption(
            value="framed_glazed_bay",
            label="Khung kính có chiều sâu",
            description="Khung cổng vào và mảng kính đứng tiết chế.",
            requires_capability="office_entrance",
        ),
        DesignOption(
            value="canopy_entry",
            label="Sảnh mái đón",
            description="Mái đón thực dụng tại khối văn phòng.",
            requires_capability="office_entrance",
        ),
        DesignOption(
            value="climate_screen",
            label="Lam chắn nắng",
            description="Lam khí hậu tại facade văn phòng có chứng cứ.",
            requires_capability="office_entrance",
        ),
    ),
    facade_rhythm_kits=(
        DesignOption(
            value="horizontal_restrained",
            label="Dải ngang tiết chế",
            description="Dải màu ngang mảnh, không chia vụn khối xưởng.",
        ),
        DesignOption(
            value="vertical_bays",
            label="Nhịp đứng",
            description="Nhấn module kết cấu và khe panel theo phương đứng.",
        ),
        DesignOption(
            value="mixed_restrained",
            label="Kết hợp cân bằng",
            description="Nhịp đứng chủ đạo với dải ngang mảnh.",
        ),
    ),
    logistics_kits=(
        DesignOption(
            value="preserve_model",
            label="Giữ theo model",
            description="Không tự phát sinh cửa dock.",
        ),
        DesignOption(
            value="authored_dock_finish",
            label="Hoàn thiện vùng dock",
            description="Chỉ hoàn thiện cửa, canopy và bumper tại vùng có chứng cứ.",
            requires_capability="logistics",
        ),
    ),
    boundary_kits=(
        DesignOption(
            value="preserve_model",
            label="Giữ theo model",
            description="Giữ nguyên biểu đạt cổng và hàng rào.",
        ),
        DesignOption(
            value="mesh_low_plinth",
            label="Lưới + chân tường thấp",
            description="Hàng rào công nghiệp thoáng, thực dụng.",
            requires_capability="boundary",
        ),
        DesignOption(
            value="vertical_bar",
            label="Song đứng",
            description="Hàng rào song đứng trung tính.",
            requires_capability="boundary",
        ),
    ),
    gate_kits=(
        DesignOption(
            value="preserve_model", label="Giữ theo model", description="Không đổi loại cổng."
        ),
        DesignOption(
            value="industrial_sliding",
            label="Cổng trượt công nghiệp",
            description="Cổng trượt tại đúng opening authored.",
            requires_capability="gate",
        ),
        DesignOption(
            value="hinged",
            label="Cổng mở cánh",
            description="Cổng mở cánh tại đúng opening authored.",
            requires_capability="gate",
        ),
    ),
    operating_scenes=(
        DesignOption(
            value="clean",
            label="Gọn, ít hoạt động",
            description="Ít xe và người, ưu tiên đọc kiến trúc.",
        ),
        DesignOption(
            value="active",
            label="Vận hành vừa phải",
            description="Hoạt động có tỷ lệ và vị trí hợp lý.",
        ),
        DesignOption(
            value="logistics",
            label="Nhấn vận hành logistics",
            description="Xe tải và vận hành chỉ tại vùng service/loading.",
            requires_capability="logistics",
        ),
    ),
    delivery_qualities=(
        DesignOption(
            value="marketing",
            label="Marketing / phát triển thiết kế",
            description="Phát triển mặt đứng trong envelope, duyệt Design Master và cả bộ ảnh.",
        ),
        DesignOption(
            value="preview",
            label="Preview tiết kiệm",
            description="Nhanh hơn để duyệt ý đồ và Design Master.",
        ),
        DesignOption(
            value="tender",
            label="Hồ sơ thầu",
            description="Độ chân thật và chi tiết cao cho phương án được chọn.",
        ),
    ),
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
            value="preserve_model",
            label="Giữ theo model",
            description="Không mở rộng cảnh quan ngoài vùng authored.",
        ),
        DesignOption(
            value="tropical_restrained",
            label="Nhiệt đới tiết chế",
            description="Cây phù hợp khí hậu, tập trung tại lối vào và dải xanh authored.",
            requires_capability="landscape",
        ),
        DesignOption(
            value="corporate_linear",
            label="Tuyến tính doanh nghiệp",
            description="Hàng cây và bụi thấp có nhịp rõ ràng.",
            requires_capability="landscape",
        ),
        DesignOption(
            value="low_maintenance",
            label="Ít bảo trì",
            description="Cây chịu hạn và bề mặt xanh đơn giản.",
            requires_capability="landscape",
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
