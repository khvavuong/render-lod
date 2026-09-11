import type { DesignFormValues, DesignOptions, UserRenderIntent } from '../types/studio';

const option = (value: string, label: string, description: string, requires_capability?: string) => ({
  value, label, description, requires_capability,
});

export const FALLBACK_DESIGN_OPTIONS: DesignOptions = {
  schema_version: '1.0.0',
  catalog_version: 'fallback-industrial-intent-v2',
  design_packages: [
    option('premium_practical', 'Thực dụng cao cấp', 'Cân bằng hồ sơ thầu và khả năng thi công.'),
    option('corporate_identity', 'Nhận diện doanh nghiệp', 'Nhấn tại khối văn phòng và điểm đến.'),
    option('tropical_industrial', 'Công nghiệp nhiệt đới', 'Giải pháp phù hợp khí hậu Việt Nam.'),
    option('minimal_logistics', 'Logistics tối giản', 'Ưu tiên vận hành và độ bền.'),
  ],
  envelope_kits: [
    option('profiled_metal_vertical', 'Tôn đứng công nghiệp', 'Tôn định hình và module thực tế.'),
    option('sandwich_panel_flat', 'Panel phẳng', 'Panel cách nhiệt với joint kỷ luật.'),
    option('panel_concrete_plinth', 'Panel + chân bê tông', 'Chân tường chịu va đập.'),
  ],
  office_entrance_kits: [
    option('preserve_model', 'Giữ theo model', 'Không thêm cấu kiện mới.'),
    option('framed_glazed_bay', 'Khung kính có chiều sâu', 'Điểm đến văn phòng tiết chế.', 'office_entrance'),
    option('canopy_entry', 'Sảnh mái đón', 'Mái đón thực dụng.', 'office_entrance'),
    option('climate_screen', 'Lam chắn nắng', 'Giải pháp khí hậu.', 'office_entrance'),
  ],
  facade_rhythm_kits: [
    option('horizontal_restrained', 'Dải ngang tiết chế', 'Giữ khối xưởng liền mạch.'),
    option('vertical_bays', 'Nhịp đứng', 'Đọc rõ module kết cấu.'),
    option('mixed_restrained', 'Kết hợp cân bằng', 'Nhịp đứng và dải ngang mảnh.'),
  ],
  logistics_kits: [
    option('preserve_model', 'Giữ theo model', 'Không tự thêm cửa dock.'),
    option('authored_dock_finish', 'Hoàn thiện vùng dock', 'Chỉ tại vùng có chứng cứ.', 'logistics'),
  ],
  boundary_kits: [
    option('preserve_model', 'Giữ theo model', 'Không phát sinh ranh mới.'),
    option('mesh_low_plinth', 'Lưới + chân tường thấp', 'Hàng rào thoáng.', 'boundary'),
    option('vertical_bar', 'Song đứng', 'Hàng rào trung tính.', 'boundary'),
  ],
  gate_kits: [
    option('preserve_model', 'Giữ theo model', 'Không đổi cổng.'),
    option('industrial_sliding', 'Cổng trượt công nghiệp', 'Tại opening authored.', 'gate'),
    option('hinged', 'Cổng mở cánh', 'Tại opening authored.', 'gate'),
  ],
  operating_scenes: [
    option('clean', 'Gọn, ít hoạt động', 'Ưu tiên đọc kiến trúc.'),
    option('active', 'Vận hành vừa phải', 'Người và xe có kiểm soát.'),
    option('logistics', 'Nhấn vận hành logistics', 'Xe tải chỉ ở service/loading.', 'logistics'),
  ],
  delivery_qualities: [
    option('preview', 'Preview tiết kiệm', 'Duyệt nhanh Design Master.'),
    option('tender', 'Hồ sơ thầu', 'Chất lượng cao sau khi chốt ý đồ.'),
  ],
  landscapes: [
    option('preserve_model', 'Giữ theo model', 'Không mở rộng vùng xanh.'),
    option('tropical_restrained', 'Nhiệt đới tiết chế', 'Cây phù hợp khí hậu.', 'landscape'),
    option('corporate_linear', 'Tuyến tính doanh nghiệp', 'Cảnh quan theo nhịp.', 'landscape'),
    option('low_maintenance', 'Ít bảo trì', 'Cây bền vững.', 'landscape'),
  ],
  realism_presets: [
    option('documentary_architectural_photo', 'Ảnh kiến trúc chân thật', 'Gần ảnh chụp hiện trường.'),
    option('premium_bid_photo', 'Ảnh hồ sơ thầu cao cấp', 'Sạch nhưng vẫn thực tế.'),
  ],
};

export const DEFAULT_FORM_VALUES: DesignFormValues = {
  projectId: '',
  designPackage: 'premium_practical',
  envelopeKit: 'profiled_metal_vertical',
  officeEntranceKit: 'preserve_model',
  facadeRhythmKit: 'mixed_restrained',
  logisticsKit: 'preserve_model',
  boundaryKit: 'preserve_model',
  gateKit: 'preserve_model',
  accentCoveragePercent: 5,
  operatingScene: 'active',
  deliveryQuality: 'preview',
  palette: {
    roof: '#E8E7E1', primary: '#ECE9E1', secondary: '#202A31',
    glass: '#294B5B', accent: '#176B4D', boundary: '#626B70', paving: '#74797A',
  },
  landscapePreset: 'tropical_restrained',
  realismPreset: 'documentary_architectural_photo',
  time: '09:30',
  creativePrompt: '',
};

export function buildUserRenderIntent(values: DesignFormValues): UserRenderIntent {
  return {
    schema_version: '1.0.0',
    design_package: values.designPackage,
    envelope_kit: values.envelopeKit,
    office_entrance_kit: values.officeEntranceKit,
    facade_rhythm_kit: values.facadeRhythmKit,
    logistics_kit: values.logisticsKit,
    boundary_kit: values.boundaryKit,
    gate_kit: values.gateKit,
    accent_coverage_percent: values.accentCoveragePercent,
    operating_scene: values.operatingScene,
    delivery_quality: values.deliveryQuality,
    material_palette: {
      roof_hex: values.palette.roof,
      primary_hex: values.palette.primary,
      secondary_hex: values.palette.secondary,
      glass_hex: values.palette.glass,
      accent_hex: values.palette.accent,
      boundary_hex: values.palette.boundary,
      paving_hex: values.palette.paving,
    },
    landscape_preset: values.landscapePreset,
    time: values.time,
    realism_preset: values.realismPreset,
    free_text: values.creativePrompt?.trim() || null,
  };
}
