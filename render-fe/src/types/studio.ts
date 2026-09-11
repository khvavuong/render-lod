export type StylePreset =
  | 'contemporary_industrial'
  | 'minimal_industrial'
  | 'corporate_industrial'
  | 'sustainable_industrial'
  | 'refined_high_tech';

export type DecorLevel = 'minimal' | 'subtle' | 'balanced' | 'expressive';
export type EntourageDensity = 'none' | 'low' | 'medium' | 'high';
export type CreativeBudget = 'strict' | 'balanced' | 'exploratory';
export type LoadingDockPolicy =
  | 'preserve_existing'
  | 'suggest_if_missing'
  | 'exact_on_eligible_facade';
export type LandscapePreset =
  | 'tropical_restrained'
  | 'corporate_linear'
  | 'low_maintenance';
export type ContextPresentation = 'authored_only' | 'neutral_industrial_massing';
export type RealismPreset =
  | 'documentary_architectural_photo'
  | 'premium_bid_photo';

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
  loadingDockPolicy: LoadingDockPolicy;
  landscapePreset: LandscapePreset;
  entourageDensity: EntourageDensity;
  creativeBudget: CreativeBudget;
  contextPresentation: ContextPresentation;
  realismPreset: RealismPreset;
  time: string;
  creativePrompt?: string;
}

export interface UserRenderIntent {
  schema_version: '1.0.0';
  style_preset: StylePreset;
  creative_budget: CreativeBudget;
  material_palette: {
    primary_hex: string;
    secondary_hex: string;
    glass_hex: string;
    accent_hex: string;
    paving_hex: string;
  };
  decor_level: DecorLevel;
  office_facade_rhythm: number;
  loading_dock_policy: LoadingDockPolicy;
  loading_dock_count: number;
  landscape_preset: LandscapePreset;
  entourage_density: EntourageDensity;
  time: string;
  context_presentation: ContextPresentation;
  realism_preset: RealismPreset;
  free_text: string | null;
}

export interface DesignOption {
  value: string;
  label: string;
  description: string;
}

export interface DesignOptions {
  schema_version: '1.0.0';
  catalog_version: string;
  styles: DesignOption[];
  decor_levels: DesignOption[];
  landscapes: DesignOption[];
  creative_budgets: DesignOption[];
  loading_dock_policies: DesignOption[];
  context_presentations: DesignOption[];
  realism_presets: DesignOption[];
}

export interface IntentWarning {
  code: string;
  field: string;
  message: string;
  ignored_text?: string | null;
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

export type CertificationState =
  | 'base_pbr'
  | 'marketing_generative_review'
  | 'geometry_certified'
  | 'approved_final';

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
  certificationState: CertificationState;
  outputs: OutputArtifact[];
  intentWarnings?: IntentWarning[];
  errorMessage?: string;
}

export interface StudioGateway {
  getDesignOptions?(): Promise<DesignOptions>;
  createDesign(values: DesignFormValues): Promise<StudioJob>;
  getJob(viewSetId: string): Promise<StudioJob>;
  approveViewSet(viewSetId: string): Promise<StudioJob>;
  retryViewSet(viewSetId: string): Promise<StudioJob>;
  createVideo(viewSetId: string): Promise<StudioVideoJob>;
  getVideoJob(videoJobId: string): Promise<StudioVideoJob>;
}
