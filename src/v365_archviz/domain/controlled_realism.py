"""Contracts for bounded refinement and deliverable certification."""

from __future__ import annotations

from enum import Enum

from pydantic import Field, model_validator

from v365_archviz.domain.common import DomainModel, UnitInterval
from v365_archviz.domain.qa import QAGate, QAStatus


class ControlClass(str, Enum):
    LOCKED = "locked"
    BOUNDED = "bounded"
    FREE = "free"


class ControlPreset(str, Enum):
    CONSERVATIVE = "conservative"
    BALANCED = "balanced"
    EXPRESSIVE = "expressive"


class TopologyPolicy(str, Enum):
    LOCKED = "locked"
    PRESERVE_BOUNDARY = "preserve_boundary"
    FREE = "free"


class AppearancePolicy(str, Enum):
    PRESERVE = "preserve"
    APPROVED_ASSETS_ONLY = "approved_assets_only"
    FREE = "free"


class ControlRule(DomainModel):
    semantic_role: str = Field(min_length=1)
    topology_policy: TopologyPolicy
    appearance_policy: AppearancePolicy
    permitted_asset_collections: tuple[str, ...] = ()
    max_variation: UnitInterval = 0.0


class ControlPolicy(DomainModel):
    schema_version: str = "1.0.0"
    preset: ControlPreset = ControlPreset.BALANCED
    rules: tuple[ControlRule, ...]

    @model_validator(mode="after")
    def validate_roles(self) -> ControlPolicy:
        roles = [rule.semantic_role for rule in self.rules]
        if len(roles) != len(set(roles)):
            raise ValueError("control policy semantic roles must be unique")
        return self


class AssetKind(str, Enum):
    MATERIAL = "material"
    ENVIRONMENT = "environment"
    VEGETATION = "vegetation"
    VEHICLE = "vehicle"
    PERSON = "person"
    SITE_FURNITURE = "site_furniture"


class AssetFile(DomainModel):
    role: str = Field(min_length=1)
    path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class MicroSurfaceDefinition(DomainModel):
    scale_per_m: float = Field(gt=0.0)
    roughness_variation: UnitInterval
    bump_strength: UnitInterval
    bump_distance_m: float = Field(gt=0.0)


class MaterialDefinition(DomainModel):
    color_source: str = Field(min_length=1)
    metallic: UnitInterval
    roughness: UnitInterval
    opacity: UnitInterval = 1.0
    transmission_weight: UnitInterval = 0.0
    ior: float = Field(default=1.5, ge=1.0, le=3.0)
    coat_weight: UnitInterval = 0.0
    coat_roughness: UnitInterval = 0.03
    texture_scale_m: float | None = Field(default=None, gt=0.0)
    micro_surface: MicroSurfaceDefinition | None = None


class AssetManifestEntry(DomainModel):
    asset_id: str = Field(min_length=1)
    kind: AssetKind
    semantic_roles: tuple[str, ...]
    physical_dimensions_m: tuple[float, float, float] | None = None
    files: tuple[AssetFile, ...] = ()
    license: str = Field(min_length=1)
    source: str = Field(min_length=1)
    renderer_compatibility: tuple[str, ...]
    memory_class: str = Field(pattern=r"^(procedural|1K|2K|4K)$")
    material: MaterialDefinition | None = None

    @model_validator(mode="after")
    def validate_kind_payload(self) -> AssetManifestEntry:
        if self.kind is AssetKind.MATERIAL and self.material is None:
            raise ValueError("material assets require a material definition")
        if self.kind is not AssetKind.MATERIAL and self.material is not None:
            raise ValueError("only material assets may define a material payload")
        return self


class AssetLibraryManifest(DomainModel):
    schema_version: str = "1.0.0"
    library_version: str = Field(min_length=1)
    assets: tuple[AssetManifestEntry, ...]

    @model_validator(mode="after")
    def validate_asset_ids(self) -> AssetLibraryManifest:
        asset_ids = [asset.asset_id for asset in self.assets]
        if len(asset_ids) != len(set(asset_ids)):
            raise ValueError("asset IDs must be unique")
        material_roles = [
            role
            for asset in self.assets
            if asset.kind is AssetKind.MATERIAL
            for role in asset.semantic_roles
        ]
        if len(material_roles) != len(set(material_roles)):
            raise ValueError("material semantic roles must resolve to exactly one asset")
        return self


class ControlMaskArtifact(DomainModel):
    control_class: ControlClass
    path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    coverage: UnitInterval


class ControlPackManifest(DomainModel):
    schema_version: str = "1.0.0"
    view_id: str = Field(min_length=1)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    policy_source_ref: str = Field(min_length=1)
    critical_edge_ref: str = Field(min_length=1)
    structure_guide_ref: str = Field(min_length=1)
    structure_guide_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    masks: tuple[ControlMaskArtifact, ...]
    overlap_pixels: int = Field(ge=0)
    uncovered_pixels: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_partition(self) -> ControlPackManifest:
        classes = [mask.control_class for mask in self.masks]
        if set(classes) != set(ControlClass) or len(classes) != len(ControlClass):
            raise ValueError("control pack must contain exactly one mask for every control class")
        if self.overlap_pixels or self.uncovered_pixels:
            raise ValueError("control masks must form a complete non-overlapping partition")
        if abs(sum(mask.coverage for mask in self.masks) - 1.0) > 1e-6:
            raise ValueError("control mask coverage must sum to one")
        return self


class CertificationState(str, Enum):
    BASE_PBR = "base_pbr"
    MARKETING_GENERATIVE_REVIEW = "marketing_generative_review"
    GEOMETRY_CERTIFIED = "geometry_certified"
    APPROVED_FINAL = "approved_final"


class CertificationEvidence(DomainModel):
    gate: QAGate
    status: QAStatus
    evidence_refs: tuple[str, ...] = ()
    message: str = Field(min_length=1)


class CertificationReport(DomainModel):
    schema_version: str = "1.0.0"
    report_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    model_revision: str = Field(min_length=1)
    design_revision: str = Field(min_length=1)
    view_set_id: str = Field(min_length=1)
    state: CertificationState
    evidence: tuple[CertificationEvidence, ...]
    reviewer: str | None = None
    decision_reason: str | None = None

    @model_validator(mode="after")
    def validate_certification(self) -> CertificationReport:
        by_gate = {item.gate: item for item in self.evidence}
        hard_gates = {
            QAGate.ARTIFACT_INTEGRITY,
            QAGate.GEOMETRY,
            QAGate.SEMANTIC,
            QAGate.MATERIAL,
            QAGate.CROSS_VIEW_APPEARANCE,
            QAGate.CAMERA,
        }
        if self.state in {
            CertificationState.GEOMETRY_CERTIFIED,
            CertificationState.APPROVED_FINAL,
        }:
            missing = hard_gates - set(by_gate)
            failed = {
                gate
                for gate in hard_gates
                if gate in by_gate
                and (
                    by_gate[gate].status is not QAStatus.PASS
                    or not by_gate[gate].evidence_refs
                )
            }
            if missing or failed:
                raise ValueError("certified output requires passing evidence for every hard gate")
        if self.state is CertificationState.APPROVED_FINAL:
            delivery_gates = {QAGate.REALISM, QAGate.AESTHETIC}
            missing_delivery = delivery_gates - set(by_gate)
            failed_delivery = {
                gate
                for gate in delivery_gates
                if gate in by_gate
                and (
                    by_gate[gate].status is not QAStatus.PASS
                    or not by_gate[gate].evidence_refs
                )
            }
            if missing_delivery or failed_delivery:
                raise ValueError(
                    "approved final output requires passing realism and aesthetic evidence"
                )
            if not self.reviewer:
                raise ValueError("approved final output requires a reviewer")
        return self
