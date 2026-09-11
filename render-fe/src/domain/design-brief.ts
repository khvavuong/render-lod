import type {
  DesignFormValues,
  DesignOptions,
  UserRenderIntent,
} from '../types/studio';

// Resilient labels only. The server catalog replaces these as soon as the application loads.
export const FALLBACK_DESIGN_OPTIONS: DesignOptions = {
  schema_version: '1.0.0',
  catalog_version: 'fallback-ui-v1',
  styles: [
    { value: 'contemporary_industrial', label: 'Công nghiệp đương đại', description: 'Phong cách mặc định.' },
    { value: 'minimal_industrial', label: 'Tối giản tinh tế', description: 'Facade tối giản.' },
    { value: 'corporate_industrial', label: 'Nhận diện doanh nghiệp', description: 'Nhấn mạnh nhận diện.' },
    { value: 'sustainable_industrial', label: 'Công nghiệp xanh', description: 'Thích ứng khí hậu.' },
    { value: 'refined_high_tech', label: 'High-tech tiết chế', description: 'Chi tiết kỹ thuật.' },
  ],
  decor_levels: [
    { value: 'minimal', label: 'Tối giản', description: 'Ít chi tiết.' },
    { value: 'subtle', label: 'Nhẹ', description: 'Chi tiết nhẹ.' },
    { value: 'balanced', label: 'Cân bằng', description: 'Mức mặc định.' },
    { value: 'expressive', label: 'Nổi bật', description: 'Nhiều điểm nhấn hơn.' },
  ],
  landscapes: [
    { value: 'tropical_restrained', label: 'Nhiệt đới tiết chế', description: 'Phù hợp khí hậu.' },
    { value: 'corporate_linear', label: 'Tuyến tính doanh nghiệp', description: 'Cảnh quan có nhịp.' },
    { value: 'low_maintenance', label: 'Ít bảo trì', description: 'Cây xanh bền vững.' },
  ],
  creative_budgets: [
    { value: 'strict', label: 'Chặt chẽ', description: 'Bám model tối đa.' },
    { value: 'balanced', label: 'Cân bằng', description: 'Làm đẹp có kiểm soát.' },
    { value: 'exploratory', label: 'Khám phá', description: 'Tăng biến thể vùng tự do.' },
  ],
  loading_dock_policies: [
    { value: 'preserve_existing', label: 'Giữ theo model', description: 'Không thêm cửa.' },
    { value: 'suggest_if_missing', label: 'Đề xuất khi thiếu', description: 'Đặt trên facade phù hợp.' },
    { value: 'exact_on_eligible_facade', label: 'Đúng số lượng', description: 'Theo số lượng yêu cầu.' },
  ],
  context_presentations: [
    { value: 'authored_only', label: 'Chỉ theo model', description: 'Không phát sinh context.' },
    { value: 'neutral_industrial_massing', label: 'Khối công nghiệp trung tính', description: 'Làm dịu context.' },
  ],
  realism_presets: [
    { value: 'documentary_architectural_photo', label: 'Ảnh kiến trúc chân thật', description: 'Gần ảnh chụp.' },
    { value: 'premium_bid_photo', label: 'Ảnh hồ sơ thầu cao cấp', description: 'Sạch và thuyết phục.' },
  ],
};

export const DEFAULT_FORM_VALUES: DesignFormValues = {
  projectId: '',
  stylePreset: 'contemporary_industrial',
  palette: {
    primary: '#ECE9E1',
    secondary: '#202A31',
    glass: '#294B5B',
    accent: '#176B4D',
    paving: '#74797A',
  },
  decorLevel: 'balanced',
  officeStoreys: 2,
  loadingDocks: 3,
  loadingDockPolicy: 'suggest_if_missing',
  landscapePreset: 'tropical_restrained',
  entourageDensity: 'low',
  creativeBudget: 'balanced',
  contextPresentation: 'authored_only',
  realismPreset: 'documentary_architectural_photo',
  time: '09:30',
  creativePrompt: '',
};

export function buildUserRenderIntent(values: DesignFormValues): UserRenderIntent {
  return {
    schema_version: '1.0.0',
    style_preset: values.stylePreset,
    creative_budget: values.creativeBudget,
    material_palette: {
      primary_hex: values.palette.primary,
      secondary_hex: values.palette.secondary,
      glass_hex: values.palette.glass,
      accent_hex: values.palette.accent,
      paving_hex: values.palette.paving,
    },
    decor_level: values.decorLevel,
    office_facade_rhythm: values.officeStoreys,
    loading_dock_policy: values.loadingDockPolicy,
    loading_dock_count: values.loadingDocks,
    landscape_preset: values.landscapePreset,
    entourage_density: values.entourageDensity,
    time: values.time,
    context_presentation: values.contextPresentation,
    realism_preset: values.realismPreset,
    free_text: values.creativePrompt?.trim() || null,
  };
}
