import type { DecorLevel, DesignBrief, DesignFormValues, StylePreset } from '../types/studio';

const STYLE_LANGUAGE: Record<
  StylePreset,
  { label: string; style: string; primary: string; secondary: string; office: string }
> = {
  contemporary_industrial: {
    label: 'Công nghiệp đương đại',
    style: 'contemporary Vietnamese industrial architecture with refined practical proportions',
    primary: 'light neutral architectural metal cladding',
    secondary: 'dark graphite metal accents',
    office: 'high-performance blue-grey architectural glazing',
  },
  minimal_industrial: {
    label: 'Tối giản tinh tế',
    style: 'minimal refined industrial architecture with disciplined facade rhythm',
    primary: 'light matte profiled metal cladding',
    secondary: 'restrained charcoal metal details',
    office: 'neutral low-reflectance architectural glazing',
  },
  corporate_industrial: {
    label: 'Nhận diện doanh nghiệp',
    style: 'professional corporate industrial campus with a clear arrival identity',
    primary: 'durable neutral insulated metal panels',
    secondary: 'precise dark metal framing',
    office: 'shaded corporate architectural glazing',
  },
  sustainable_industrial: {
    label: 'Công nghiệp xanh',
    style: 'climate-responsive sustainable industrial campus suitable for Vietnam',
    primary: 'high-albedo neutral metal cladding',
    secondary: 'weather-resistant deep neutral accents',
    office: 'solar-controlled architectural glazing',
  },
  refined_high_tech: {
    label: 'High-tech tiết chế',
    style: 'restrained high-tech industrial architecture with buildable technical detailing',
    primary: 'precision light-grey metal envelope',
    secondary: 'graphite technical metalwork',
    office: 'high-performance cool-neutral glazing',
  },
};

const DECOR_ARTICULATION: Record<
  DecorLevel,
  DesignBrief['facade_articulation']
> = {
  minimal: {
    plinth_height_m: 0.75,
    parapet_band_height_m: 0.45,
    office_glazing_ratio: 0.36,
    feature_frame_depth_m: 0.25,
    entrance_canopy_projection_m: 1.4,
    vertical_fin_count: 0,
    accent_bay_interval: 14,
  },
  subtle: {
    plinth_height_m: 0.8,
    parapet_band_height_m: 0.55,
    office_glazing_ratio: 0.42,
    feature_frame_depth_m: 0.4,
    entrance_canopy_projection_m: 1.8,
    vertical_fin_count: 2,
    accent_bay_interval: 12,
  },
  balanced: {
    plinth_height_m: 0.9,
    parapet_band_height_m: 0.65,
    office_glazing_ratio: 0.48,
    feature_frame_depth_m: 0.75,
    entrance_canopy_projection_m: 2.4,
    vertical_fin_count: 3,
    accent_bay_interval: 10,
  },
  expressive: {
    plinth_height_m: 1,
    parapet_band_height_m: 0.8,
    office_glazing_ratio: 0.58,
    feature_frame_depth_m: 1.1,
    entrance_canopy_projection_m: 3,
    vertical_fin_count: 6,
    accent_bay_interval: 7,
  },
};

export const STYLE_OPTIONS = Object.entries(STYLE_LANGUAGE).map(([value, item]) => ({
  value: value as StylePreset,
  label: item.label,
}));

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
  landscapeCharacter: 'Cây xanh nhiệt đới tiết chế, tập trung tại lối vào',
  entourageDensity: 'low',
  time: '09:30',
  creativePrompt: '',
};

export function buildDesignBrief(values: DesignFormValues): DesignBrief {
  const language = STYLE_LANGUAGE[values.stylePreset];
  return {
    schema_version: '1.0.0',
    project_id: values.projectId.trim(),
    design_language: {
      style: language.style,
      primary_material: language.primary,
      secondary_material: language.secondary,
      office_material: language.office,
      accent: 'restrained project accent used only at selected entrance and facade bays',
    },
    environment: {
      time: values.time,
      weather: 'clear bright morning with soft atmospheric depth',
      sun_azimuth_deg: 132,
      sun_elevation_deg: 48,
      white_balance_k: 5600,
    },
    material_palette: {
      primary_hex: values.palette.primary,
      secondary_hex: values.palette.secondary,
      glass_hex: values.palette.glass,
      accent_hex: values.palette.accent,
      paving_hex: values.palette.paving,
    },
    facade_articulation: DECOR_ARTICULATION[values.decorLevel],
    presentation: {
      landscape_character: values.landscapeCharacter,
      paving_character: 'clean light-grey industrial concrete with precise drainage edges',
      entourage_density: values.entourageDensity,
    },
    site_design: {
      preserve_transport_geometry: true,
      preserve_landscape_boundaries: true,
      context_render_mode: 'translucent_massing',
      context_opacity: 0.24,
      surrounding_context_mode: 'procedural_perimeter',
      surrounding_context_count: 6,
      surrounding_landscape_buffer: true,
    },
    design_preferences: {
      style_preset: values.stylePreset,
      decor_level: values.decorLevel,
      requested_office_storeys: values.officeStoreys,
      creative_prompt: values.creativePrompt?.trim() || null,
    },
    focus_building_ids: [],
    context_building_ids: [],
    panel_module_m: 1.2,
    loading_docks_per_main_facade: values.loadingDocks,
    add_office_entrances: true,
    roof_type: 'symmetric low-slope gable profiled-metal roof fitted inside LOD100 envelope',
    roof_slope_deg: 7,
    roof_eave_overhang_m: 0.75,
    roof_ridge_orientation: 'long_axis',
    roof_grouping_mode: 'continuous_rows',
    roof_group_gap_tolerance_m: 10,
    solar_panels: false,
    grammar_version: 'industrial-grammar-v3-continuous-roof',
    asset_library_version: 'baseline-assets-v2',
  };
}
