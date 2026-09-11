"""Design DNA contracts and deterministic validation rules."""

from __future__ import annotations

from enum import Enum

from pydantic import Field, model_validator

from v365_archviz.domain.common import DomainModel, PositiveMeters, UnitInterval
from v365_archviz.domain.scene import BoundingBox


class DesignEvidenceState(str, Enum):
    AUTHORED = "authored"
    INFERRED_PROPOSAL = "inferred_proposal"
    NEEDS_REVIEW = "needs_review"
    UNSUPPORTED = "unsupported"


class LoadingDock(DomainModel):
    dock_id: str = Field(min_length=1)
    u: UnitInterval
    width_m: PositiveMeters
    evidence_state: DesignEvidenceState = DesignEvidenceState.INFERRED_PROPOSAL


class Entrance(DomainModel):
    u: UnitInterval
    width_m: PositiveMeters
    evidence_state: DesignEvidenceState = DesignEvidenceState.INFERRED_PROPOSAL


class MaterialPalette(DomainModel):
    roof_hex: str = Field(default="#E8E7E1", pattern=r"^#[0-9A-Fa-f]{6}$")
    primary_hex: str = Field(default="#E7E5DF", pattern=r"^#[0-9A-Fa-f]{6}$")
    secondary_hex: str = Field(default="#252B31", pattern=r"^#[0-9A-Fa-f]{6}$")
    glass_hex: str = Field(default="#315263", pattern=r"^#[0-9A-Fa-f]{6}$")
    accent_hex: str = Field(default="#2F6B4F", pattern=r"^#[0-9A-Fa-f]{6}$")
    boundary_hex: str = Field(default="#626B70", pattern=r"^#[0-9A-Fa-f]{6}$")
    paving_hex: str = Field(default="#777B7A", pattern=r"^#[0-9A-Fa-f]{6}$")


class FacadeArticulation(DomainModel):
    """Dimensioned facade grammar applicable across projects and model scales."""

    plinth_height_m: float = Field(default=0.75, ge=0.0, le=2.5)
    parapet_band_height_m: float = Field(default=0.55, ge=0.0, le=2.5)
    office_glazing_ratio: float = Field(default=0.72, ge=0.25, le=0.95)
    feature_frame_depth_m: float = Field(default=0.55, ge=0.05, le=2.5)
    entrance_canopy_projection_m: float = Field(default=1.8, ge=0.0, le=6.0)
    vertical_fin_count: int = Field(default=4, ge=0, le=16)
    accent_bay_interval: int = Field(default=6, ge=0, le=20)


class PresentationStrategy(DomainModel):
    landscape_character: str = Field(
        default="restrained climate-appropriate planting", min_length=1
    )
    paving_character: str = Field(default="clean durable industrial paving", min_length=1)
    entourage_density: str = Field(default="low", pattern=r"^(none|low|medium|high)$")


class FacadeDesign(DomainModel):
    surface_id: str = Field(min_length=1)
    panel_module_m: PositiveMeters = Field(ge=0.8, le=1.5)
    office_entrance: Entrance | None = None
    loading_docks: tuple[LoadingDock, ...] = ()
    articulation: FacadeArticulation = Field(default_factory=FacadeArticulation)

    @model_validator(mode="after")
    def validate_docks(self) -> FacadeDesign:
        dock_ids = [dock.dock_id for dock in self.loading_docks]
        if len(dock_ids) != len(set(dock_ids)):
            raise ValueError("loading dock IDs must be unique within a facade")
        return self


class RoofDesign(DomainModel):
    roof_type: str = Field(min_length=1)
    solar_panels: bool = False
    slope_deg: float = Field(default=7.0, ge=0.0, le=25.0)
    eave_overhang_m: float = Field(default=0.6, ge=0.0, le=3.0)
    ridge_orientation: str = Field(default="long_axis", pattern=r"^(long_axis|short_axis)$")


class BuildingTreatment(str, Enum):
    FOCUS = "focus"
    AUXILIARY = "auxiliary"
    CONTEXT = "context"


class StylePreset(str, Enum):
    CONTEMPORARY_INDUSTRIAL = "contemporary_industrial"
    MINIMAL_INDUSTRIAL = "minimal_industrial"
    CORPORATE_INDUSTRIAL = "corporate_industrial"
    SUSTAINABLE_INDUSTRIAL = "sustainable_industrial"
    REFINED_HIGH_TECH = "refined_high_tech"


class DecorLevel(str, Enum):
    MINIMAL = "minimal"
    SUBTLE = "subtle"
    BALANCED = "balanced"
    EXPRESSIVE = "expressive"


class DesignPreferences(DomainModel):
    """User-facing intent that may refine finishes but never override LOD geometry."""

    style_preset: StylePreset = StylePreset.CONTEMPORARY_INDUSTRIAL
    decor_level: DecorLevel = DecorLevel.BALANCED
    requested_office_storeys: int | None = Field(default=None, ge=1, le=8)
    creative_prompt: str | None = Field(default=None, max_length=1000)
    design_package: str = Field(default="premium_practical", min_length=1)
    envelope_kit: str = Field(default="profiled_metal_vertical", min_length=1)
    office_entrance_kit: str = Field(default="preserve_model", min_length=1)
    facade_rhythm_kit: str = Field(default="mixed_restrained", min_length=1)
    logistics_kit: str = Field(default="preserve_model", min_length=1)
    boundary_kit: str = Field(default="preserve_model", min_length=1)
    gate_kit: str = Field(default="preserve_model", min_length=1)
    accent_coverage_percent: int = Field(default=5, ge=3, le=8)


class BuildingDesign(DomainModel):
    building_id: str = Field(min_length=1)
    treatment: BuildingTreatment = BuildingTreatment.FOCUS
    roof: RoofDesign
    facades: tuple[FacadeDesign, ...] = ()


class RoofAssembly(DomainModel):
    """One continuous roof spanning one or more aligned LOD100 source blocks."""

    assembly_id: str = Field(min_length=1)
    building_ids: tuple[str, ...] = Field(min_length=1)
    bounding_box: BoundingBox
    roof: RoofDesign

    @model_validator(mode="after")
    def validate_buildings(self) -> RoofAssembly:
        if len(self.building_ids) != len(set(self.building_ids)):
            raise ValueError("roof assembly building IDs must be unique")
        return self


class SiteDesign(DomainModel):
    preserve_transport_geometry: bool = True
    preserve_landscape_boundaries: bool = True
    context_render_mode: str = Field(
        default="translucent_massing", pattern=r"^translucent_massing$"
    )
    context_opacity: float = Field(default=0.28, ge=0.08, le=0.65)
    surrounding_context_mode: str = Field(
        default="authored_only",
        pattern=r"^(authored_only|procedural_perimeter|conceptual_industrial_park|none)$",
    )
    surrounding_context_count: int = Field(default=0, ge=0, le=12)
    surrounding_landscape_buffer: bool = False

    @model_validator(mode="after")
    def validate_surrounding_context(self) -> SiteDesign:
        if self.surrounding_context_mode in {"authored_only", "none"} and (
            self.surrounding_context_count
        ):
            raise ValueError("non-procedural context cannot request conceptual massings")
        return self


class ContextRoad(DomainModel):
    road_id: str = Field(min_length=1)
    bounding_box: BoundingBox


class ContextProxyBuilding(DomainModel):
    proxy_id: str = Field(min_length=1)
    bounding_box: BoundingBox
    ridge_orientation: str = Field(default="long_axis", pattern=r"^(long_axis|short_axis)$")
    opacity: float = Field(default=0.28, ge=0.08, le=0.40)
    conceptual: bool = True


class IndustrialContextPlan(DomainModel):
    """Deterministic off-site planning geometry; never represented as authored fact."""

    schema_version: str = "1.0.0"
    mode: str = Field(
        default="authored_only",
        pattern=r"^(authored_only|conceptual_industrial_park|none)$",
    )
    seed: str = Field(min_length=1)
    ground: BoundingBox | None = None
    roads: tuple[ContextRoad, ...] = ()
    proxy_buildings: tuple[ContextProxyBuilding, ...] = ()
    provenance: str = "model-relative conceptual context"


class DesignLanguage(DomainModel):
    style: str = Field(min_length=1)
    primary_material: str = Field(min_length=1)
    secondary_material: str = Field(min_length=1)
    office_material: str = Field(min_length=1)
    accent: str | None = None


class EnvironmentDesign(DomainModel):
    time: str = Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    weather: str = Field(min_length=1)
    sun_azimuth_deg: float = Field(ge=0.0, lt=360.0)
    sun_elevation_deg: float = Field(ge=-90.0, le=90.0)
    white_balance_k: int = Field(ge=1000, le=20000)


class DesignBrief(DomainModel):
    """Project input; no visual language is inferred from a repository fixture."""

    schema_version: str = "1.0.0"
    project_id: str = Field(min_length=1)
    design_language: DesignLanguage
    environment: EnvironmentDesign
    material_palette: MaterialPalette = Field(default_factory=MaterialPalette)
    facade_articulation: FacadeArticulation = Field(default_factory=FacadeArticulation)
    presentation: PresentationStrategy = Field(default_factory=PresentationStrategy)
    site_design: SiteDesign = Field(default_factory=SiteDesign)
    design_preferences: DesignPreferences = Field(default_factory=DesignPreferences)
    focus_building_ids: tuple[str, ...] = ()
    context_building_ids: tuple[str, ...] = ()
    panel_module_m: PositiveMeters = Field(ge=0.8, le=1.5)
    loading_docks_per_main_facade: int = Field(default=0, ge=0, le=12)
    add_office_entrances: bool = False
    roof_type: str = Field(min_length=1)
    roof_slope_deg: float = Field(default=7.0, ge=0.0, le=25.0)
    roof_eave_overhang_m: float = Field(default=0.6, ge=0.0, le=3.0)
    roof_ridge_orientation: str = Field(default="long_axis", pattern=r"^(long_axis|short_axis)$")
    roof_grouping_mode: str = Field(
        default="per_element", pattern=r"^(per_element|continuous_rows)$"
    )
    roof_group_gap_tolerance_m: float = Field(default=2.0, ge=0.0, le=30.0)
    solar_panels: bool = False
    grammar_version: str = Field(min_length=1)
    asset_library_version: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_building_scope(self) -> DesignBrief:
        focus = set(self.focus_building_ids)
        context = set(self.context_building_ids)
        if len(focus) != len(self.focus_building_ids):
            raise ValueError("focus building IDs must be unique")
        if len(context) != len(self.context_building_ids):
            raise ValueError("context building IDs must be unique")
        if overlap := focus & context:
            raise ValueError(f"building IDs cannot be both focus and context: {sorted(overlap)}")
        return self


class DesignDNA(DomainModel):
    schema_version: str = "1.0.0"
    project_id: str = Field(min_length=1)
    design_revision: str = Field(min_length=1)
    design_language: DesignLanguage
    environment: EnvironmentDesign
    material_palette: MaterialPalette = Field(default_factory=MaterialPalette)
    presentation: PresentationStrategy = Field(default_factory=PresentationStrategy)
    site_design: SiteDesign = Field(default_factory=SiteDesign)
    industrial_context: IndustrialContextPlan | None = None
    design_preferences: DesignPreferences = Field(default_factory=DesignPreferences)
    buildings: tuple[BuildingDesign, ...]
    roof_assemblies: tuple[RoofAssembly, ...] = ()
    grammar_version: str = Field(min_length=1)
    asset_library_version: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_identifiers(self) -> DesignDNA:
        building_ids = [building.building_id for building in self.buildings]
        if len(building_ids) != len(set(building_ids)):
            raise ValueError("building IDs must be unique")
        surface_ids = [
            facade.surface_id for building in self.buildings for facade in building.facades
        ]
        if len(surface_ids) != len(set(surface_ids)):
            raise ValueError("facade surface IDs must be unique")
        building_id_set = set(building_ids)
        roof_ids = [
            building_id
            for assembly in self.roof_assemblies
            for building_id in assembly.building_ids
        ]
        if len(roof_ids) != len(set(roof_ids)):
            raise ValueError("a building cannot belong to multiple roof assemblies")
        if missing := set(roof_ids) - building_id_set:
            raise ValueError(f"roof assemblies reference missing buildings: {sorted(missing)}")
        return self
