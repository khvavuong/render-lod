export type DesignPackage =
  | 'premium_practical'
  | 'corporate_identity'
  | 'tropical_industrial'
  | 'minimal_logistics';
export type EnvelopeKit =
  | 'profiled_metal_vertical'
  | 'sandwich_panel_flat'
  | 'panel_concrete_plinth';
export type OfficeEntranceKit =
  | 'preserve_model'
  | 'framed_glazed_bay'
  | 'canopy_entry'
  | 'climate_screen';
export type FacadeRhythmKit =
  | 'horizontal_restrained'
  | 'vertical_bays'
  | 'mixed_restrained';
export type LogisticsKit = 'preserve_model' | 'authored_dock_finish';
export type BoundaryKit = 'preserve_model' | 'mesh_low_plinth' | 'vertical_bar';
export type GateKit = 'preserve_model' | 'industrial_sliding' | 'hinged';
export type OperatingScene = 'clean' | 'active' | 'logistics';
export type DeliveryQuality = 'preview' | 'marketing' | 'tender';
export type LandscapePreset =
  | 'preserve_model'
  | 'tropical_restrained'
  | 'corporate_linear'
  | 'low_maintenance';
export type RealismPreset =
  | 'documentary_architectural_photo'
  | 'premium_bid_photo';

export interface MaterialPalette {
  roof: string;
  primary: string;
  secondary: string;
  glass: string;
  accent: string;
  boundary: string;
  paving: string;
}

export interface DesignFormValues {
  projectId: string;
  modelFile?: File;
  designPackage: DesignPackage;
  envelopeKit: EnvelopeKit;
  officeEntranceKit: OfficeEntranceKit;
  facadeRhythmKit: FacadeRhythmKit;
  logisticsKit: LogisticsKit;
  boundaryKit: BoundaryKit;
  gateKit: GateKit;
  accentCoveragePercent: 3 | 5 | 8;
  operatingScene: OperatingScene;
  deliveryQuality: DeliveryQuality;
  palette: MaterialPalette;
  landscapePreset: LandscapePreset;
  realismPreset: RealismPreset;
  time: string;
  creativePrompt?: string;
  factoryDesignReference?: File;
  contextRealismReference?: File;
  constructionMaterialReference?: File;
  referenceLedPilot?: boolean;
}

export interface UserRenderIntent {
  schema_version: '1.0.0';
  design_package: DesignPackage;
  envelope_kit: EnvelopeKit;
  office_entrance_kit: OfficeEntranceKit;
  facade_rhythm_kit: FacadeRhythmKit;
  logistics_kit: LogisticsKit;
  boundary_kit: BoundaryKit;
  gate_kit: GateKit;
  accent_coverage_percent: number;
  operating_scene: OperatingScene;
  delivery_quality: DeliveryQuality;
  material_palette: {
    roof_hex: string;
    primary_hex: string;
    secondary_hex: string;
    glass_hex: string;
    accent_hex: string;
    boundary_hex: string;
    paving_hex: string;
  };
  landscape_preset: LandscapePreset;
  time: string;
  realism_preset: RealismPreset;
  free_text: string | null;
}

export interface DesignOption {
  value: string;
  label: string;
  description: string;
  requires_capability?: string | null;
}

export interface DesignOptions {
  schema_version: '1.0.0';
  catalog_version: string;
  design_packages: DesignOption[];
  envelope_kits: DesignOption[];
  office_entrance_kits: DesignOption[];
  facade_rhythm_kits: DesignOption[];
  logistics_kits: DesignOption[];
  boundary_kits: DesignOption[];
  gate_kits: DesignOption[];
  operating_scenes: DesignOption[];
  delivery_qualities: DesignOption[];
  landscapes: DesignOption[];
  realism_presets: DesignOption[];
}

export interface IntentWarning {
  code: string;
  field: string;
  message: string;
  ignored_text?: string | null;
}

export interface ComponentCapability {
  key: string;
  label: string;
  supported: boolean;
  evidence_count: number;
  evidence_ids: string[];
  reason: string;
}

export interface ModelDesignCapabilities {
  schema_version: string;
  model_revision: string;
  components: ComponentCapability[];
  warnings: string[];
}

export interface PreparedModel {
  modelRevision: string;
  fileName: string;
  capabilities: ModelDesignCapabilities;
}

export interface DesignPreview {
  modelRevision: string;
  previewToken: string;
  normalizedIntent: UserRenderIntent;
  capabilities: ModelDesignCapabilities;
  industrialContext: {
    mode: string;
    seed: string;
    roads: unknown[];
    proxy_buildings: unknown[];
  };
  warnings: IntentWarning[];
}

export type WorkflowState =
  | 'idle' | 'submitting' | 'resolving_model' | 'extracting_scene'
  | 'classifying_scene' | 'design_planning' | 'design_validation' | 'needs_input'
  | 'building_scene' | 'planning_cameras' | 'rendering_passes' | 'generating_viewset'
  | 'design_master_review' | 'validating' | 'human_review' | 'composing_board'
  | 'generating_video' | 'completed' | 'repairing' | 'failed';
export type OutputKind = 'image' | 'board' | 'video';
export type CertificationState =
  | 'base_pbr' | 'marketing_generative_review' | 'geometry_certified' | 'approved_final';
export type VideoJobState =
  | 'queued' | 'planning' | 'generating' | 'assembling' | 'completed' | 'failed';

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
  generationPolicy?: string;
  proposalSelected?: boolean;
  outputs: OutputArtifact[];
  intentWarnings?: IntentWarning[];
  errorMessage?: string;
}

export interface StudioGateway {
  getDesignOptions?(): Promise<DesignOptions>;
  prepareModel(file: File): Promise<PreparedModel>;
  previewDesign(values: DesignFormValues, model: PreparedModel): Promise<DesignPreview>;
  createDesign(
    values: DesignFormValues,
    model?: PreparedModel,
    previewToken?: string,
  ): Promise<StudioJob>;
  getJob(viewSetId: string): Promise<StudioJob>;
  approveViewSet(viewSetId: string): Promise<StudioJob>;
  rejectDesignMaster(viewSetId: string): Promise<StudioJob>;
  rejectViewSet(viewSetId: string): Promise<StudioJob>;
  retryViewSet(viewSetId: string): Promise<StudioJob>;
  createVideo(viewSetId: string): Promise<StudioVideoJob>;
  getVideoJob(videoJobId: string): Promise<StudioVideoJob>;
}
