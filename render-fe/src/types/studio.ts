export type StylePreset =
  | 'contemporary_industrial'
  | 'minimal_industrial'
  | 'corporate_industrial'
  | 'sustainable_industrial'
  | 'refined_high_tech';

export type DecorLevel = 'minimal' | 'subtle' | 'balanced' | 'expressive';
export type EntourageDensity = 'none' | 'low' | 'medium' | 'high';

export interface MaterialPalette {
  primary: string;
  secondary: string;
  glass: string;
  accent: string;
  paving: string;
}

export interface DesignFormValues {
  projectId: string;
  modelFile?: File;
  stylePreset: StylePreset;
  palette: MaterialPalette;
  decorLevel: DecorLevel;
  officeStoreys: number;
  loadingDocks: number;
  landscapeCharacter: string;
  entourageDensity: EntourageDensity;
  time: string;
  creativePrompt?: string;
}

export interface DesignBrief {
  schema_version: '1.0.0';
  project_id: string;
  design_language: {
    style: string;
    primary_material: string;
    secondary_material: string;
    office_material: string;
    accent: string;
  };
  environment: {
    time: string;
    weather: string;
    sun_azimuth_deg: number;
    sun_elevation_deg: number;
    white_balance_k: number;
  };
  material_palette: {
    primary_hex: string;
    secondary_hex: string;
    glass_hex: string;
    accent_hex: string;
    paving_hex: string;
  };
  facade_articulation: {
    plinth_height_m: number;
    parapet_band_height_m: number;
    office_glazing_ratio: number;
    feature_frame_depth_m: number;
    entrance_canopy_projection_m: number;
    vertical_fin_count: number;
    accent_bay_interval: number;
  };
  presentation: {
    landscape_character: string;
    paving_character: string;
    entourage_density: EntourageDensity;
  };
  site_design: {
    preserve_transport_geometry: true;
    preserve_landscape_boundaries: true;
    context_render_mode: 'translucent_massing';
    context_opacity: number;
    surrounding_context_mode: 'procedural_perimeter';
    surrounding_context_count: number;
    surrounding_landscape_buffer: true;
  };
  design_preferences: {
    style_preset: StylePreset;
    decor_level: DecorLevel;
    requested_office_storeys: number;
    creative_prompt: string | null;
  };
  focus_building_ids: string[];
  context_building_ids: string[];
  panel_module_m: number;
  loading_docks_per_main_facade: number;
  add_office_entrances: boolean;
  roof_type: string;
  roof_slope_deg: number;
  roof_eave_overhang_m: number;
  roof_ridge_orientation: 'long_axis';
  roof_grouping_mode: 'continuous_rows';
  roof_group_gap_tolerance_m: number;
  solar_panels: false;
  grammar_version: string;
  asset_library_version: string;
}

export type WorkflowState =
  | 'idle'
  | 'submitting'
  | 'resolving_model'
  | 'extracting_scene'
  | 'classifying_scene'
  | 'design_planning'
  | 'design_validation'
  | 'needs_input'
  | 'building_scene'
  | 'planning_cameras'
  | 'rendering_passes'
  | 'generating_viewset'
  | 'validating'
  | 'human_review'
  | 'composing_board'
  | 'generating_video'
  | 'completed'
  | 'repairing'
  | 'failed';

export type OutputKind = 'image' | 'board' | 'video';

export type VideoJobState =
  | 'queued'
  | 'planning'
  | 'generating'
  | 'assembling'
  | 'completed'
  | 'failed';

export interface StudioVideoJob {
  videoJobId: string;
  viewSetId: string;
  state: VideoJobState;
  estimatedCostUsd: number;
  outputUrl?: string;
  errorMessage?: string;
}

export interface OutputArtifact {
  id: string;
  kind: OutputKind;
  title: string;
  url: string;
  view_id?: string;
  created_at?: string;
}

export interface StudioJob {
  jobId: string;
  traceId: string;
  viewSetId: string;
  designRevision: string;
  state: WorkflowState;
  outputs: OutputArtifact[];
  errorMessage?: string;
}

export interface StudioGateway {
  createDesign(values: DesignFormValues): Promise<StudioJob>;
  getJob(viewSetId: string): Promise<StudioJob>;
  createVideo(viewSetId: string): Promise<StudioVideoJob>;
  getVideoJob(videoJobId: string): Promise<StudioVideoJob>;
}
