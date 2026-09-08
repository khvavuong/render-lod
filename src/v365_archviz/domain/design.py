"""Design DNA contracts and deterministic validation rules."""

from __future__ import annotations

from enum import Enum

from pydantic import Field, model_validator

from v365_archviz.domain.common import DomainModel, PositiveMeters, UnitInterval


class LoadingDock(DomainModel):
    dock_id: str = Field(min_length=1)
    u: UnitInterval
    width_m: PositiveMeters


class Entrance(DomainModel):
    u: UnitInterval
    width_m: PositiveMeters


class MaterialPalette(DomainModel):
    primary_hex: str = Field(default="#E7E5DF", pattern=r"^#[0-9A-Fa-f]{6}$")
    secondary_hex: str = Field(default="#252B31", pattern=r"^#[0-9A-Fa-f]{6}$")
    glass_hex: str = Field(default="#315263", pattern=r"^#[0-9A-Fa-f]{6}$")
    accent_hex: str = Field(default="#2F6B4F", pattern=r"^#[0-9A-Fa-f]{6}$")
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
    CONTEXT = "context"


class BuildingDesign(DomainModel):
    building_id: str = Field(min_length=1)
    treatment: BuildingTreatment = BuildingTreatment.FOCUS
    roof: RoofDesign
    facades: tuple[FacadeDesign, ...] = ()


class SiteDesign(DomainModel):
    preserve_transport_geometry: bool = True
    preserve_landscape_boundaries: bool = True
    context_render_mode: str = Field(
        default="translucent_massing", pattern=r"^translucent_massing$"
    )
    context_opacity: float = Field(default=0.28, ge=0.08, le=0.65)


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
    focus_building_ids: tuple[str, ...] = ()
    context_building_ids: tuple[str, ...] = ()
    panel_module_m: PositiveMeters = Field(ge=0.8, le=1.5)
    loading_docks_per_main_facade: int = Field(default=0, ge=0, le=12)
    add_office_entrances: bool = False
    roof_type: str = Field(min_length=1)
    roof_slope_deg: float = Field(default=7.0, ge=0.0, le=25.0)
    roof_eave_overhang_m: float = Field(default=0.6, ge=0.0, le=3.0)
    roof_ridge_orientation: str = Field(default="long_axis", pattern=r"^(long_axis|short_axis)$")
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
    buildings: tuple[BuildingDesign, ...]
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
        return self
