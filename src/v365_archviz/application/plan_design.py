"""Compile a project-supplied brief into scene-bound Design DNA."""

from __future__ import annotations

import hashlib
from pathlib import Path

from v365_archviz.artifacts import atomic_write
from v365_archviz.domain.design import (
    BuildingDesign,
    BuildingTreatment,
    DesignBrief,
    DesignDNA,
    Entrance,
    FacadeDesign,
    LoadingDock,
    RoofDesign,
)
from v365_archviz.domain.scene import CanonicalScene, SceneElement, SceneSurface, SemanticRole


def _element_surfaces(scene: CanonicalScene, element: SceneElement) -> tuple[SceneSurface, ...]:
    return tuple(
        surface for surface in scene.surfaces if surface.element_id == element.scene_element_id
    )


def _loading_docks(surface: SceneSurface, count: int) -> tuple[LoadingDock, ...]:
    return tuple(
        LoadingDock(
            dock_id=f"{surface.surface_id}:dock-{index + 1:02d}",
            u=(index + 1) / (count + 1),
            width_m=min(4.2, surface.width_m / (count + 2)),
        )
        for index in range(count)
    )


class PlanDesign:
    """Compile a supplied project brief into immutable, scene-bound Design DNA."""

    @staticmethod
    def revision(scene: CanonicalScene, brief: DesignBrief) -> str:
        revision_payload = f"{scene.source.version_id}\n{brief.model_dump_json()}".encode()
        return f"R01-{hashlib.sha256(revision_payload).hexdigest()[:12]}"

    def revision_from_files(self, scene_path: Path, brief_path: Path) -> str:
        scene = CanonicalScene.model_validate_json(scene_path.read_text(encoding="utf-8"))
        brief = DesignBrief.model_validate_json(brief_path.read_text(encoding="utf-8"))
        return self.revision(scene, brief)

    def execute(self, scene_path: Path, brief_path: Path) -> DesignDNA:
        scene = CanonicalScene.model_validate_json(scene_path.read_text(encoding="utf-8"))
        brief = DesignBrief.model_validate_json(brief_path.read_text(encoding="utf-8"))
        buildable_ids = {
            element.scene_element_id
            for element in scene.elements
            if _element_surfaces(scene, element)
        }
        requested_ids = set(brief.focus_building_ids) | set(brief.context_building_ids)
        if missing := requested_ids - buildable_ids:
            raise ValueError(f"design brief references unknown building IDs: {sorted(missing)}")
        buildings: list[BuildingDesign] = []
        for element in scene.elements:
            surfaces = _element_surfaces(scene, element)
            if not surfaces:
                continue
            treatment = (
                BuildingTreatment.FOCUS
                if (
                    element.scene_element_id in brief.focus_building_ids
                    or (
                        not brief.focus_building_ids
                        and element.scene_element_id not in brief.context_building_ids
                    )
                )
                else BuildingTreatment.CONTEXT
            )
            facades = tuple(
                FacadeDesign(
                    surface_id=surface.surface_id,
                    panel_module_m=brief.panel_module_m,
                    office_entrance=(
                        Entrance(u=0.5, width_m=min(2.4, surface.width_m * 0.25))
                        if brief.add_office_entrances
                        and element.semantic_role is SemanticRole.OFFICE_BLOCK
                        and surface.semantic_role is SemanticRole.PRIMARY_FACADE
                        else None
                    ),
                    loading_docks=(
                        _loading_docks(surface, brief.loading_docks_per_main_facade)
                        if element.semantic_role is SemanticRole.MAIN_SHED
                        and surface.semantic_role is SemanticRole.PRIMARY_FACADE
                        else ()
                    ),
                    articulation=brief.facade_articulation,
                )
                for surface in surfaces
            )
            buildings.append(
                BuildingDesign(
                    building_id=element.scene_element_id,
                    treatment=treatment,
                    roof=RoofDesign(
                        roof_type=brief.roof_type,
                        solar_panels=brief.solar_panels,
                        slope_deg=brief.roof_slope_deg,
                        eave_overhang_m=brief.roof_eave_overhang_m,
                        ridge_orientation=brief.roof_ridge_orientation,
                    ),
                    facades=facades if treatment is BuildingTreatment.FOCUS else (),
                )
            )
        design_revision = self.revision(scene, brief)
        design = DesignDNA(
            project_id=brief.project_id,
            design_revision=design_revision,
            design_language=brief.design_language,
            environment=brief.environment,
            material_palette=brief.material_palette,
            presentation=brief.presentation,
            site_design=brief.site_design,
            buildings=tuple(buildings),
            grammar_version=brief.grammar_version,
            asset_library_version=brief.asset_library_version,
        )
        output = scene_path.parent / "designs" / design_revision / "design_dna.json"
        atomic_write(output, design.model_dump_json(indent=2).encode() + b"\n")
        return design
