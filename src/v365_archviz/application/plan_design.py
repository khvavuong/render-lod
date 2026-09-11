"""Compile a project-supplied brief into scene-bound Design DNA."""

from __future__ import annotations

import hashlib
from pathlib import Path

from v365_archviz.application.plan_industrial_context import PlanIndustrialContext
from v365_archviz.artifacts import atomic_write
from v365_archviz.domain.design import (
    BuildingDesign,
    BuildingTreatment,
    DesignBrief,
    DesignDNA,
    Entrance,
    FacadeDesign,
    LoadingDock,
    RoofAssembly,
    RoofDesign,
)
from v365_archviz.domain.scene import (
    BoundingBox,
    CanonicalScene,
    SceneElement,
    SceneSurface,
    SemanticRole,
)


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


def _campus_center(scene: CanonicalScene) -> tuple[float, float]:
    buildings = [
        element
        for element in scene.elements
        if element.semantic_role in {SemanticRole.MAIN_SHED, SemanticRole.OFFICE_BLOCK}
    ]
    candidates = buildings or list(scene.elements)
    return (
        (
            min(item.bounding_box.minimum[0] for item in candidates)
            + max(item.bounding_box.maximum[0] for item in candidates)
        )
        / 2,
        (
            min(item.bounding_box.minimum[1] for item in candidates)
            + max(item.bounding_box.maximum[1] for item in candidates)
        )
        / 2,
    )


def _element_center(element: SceneElement) -> tuple[float, float]:
    return (
        (element.bounding_box.minimum[0] + element.bounding_box.maximum[0]) / 2,
        (element.bounding_box.minimum[1] + element.bounding_box.maximum[1]) / 2,
    )


def _front_surface(
    surfaces: tuple[SceneSurface, ...], target: tuple[float, float], face_toward: bool = True
) -> SceneSurface | None:
    """Choose one courtyard-facing facade; never place entrances/docks on every side."""

    horizontal = [surface for surface in surfaces if abs(surface.frame.normal[2]) < 0.1]
    if not horizontal:
        return None

    def distance(surface: SceneSurface) -> float:
        center = tuple(
            surface.frame.origin[index]
            + surface.frame.u_axis[index] * surface.width_m / 2
            + surface.frame.v_axis[index] * surface.height_m / 2
            for index in range(3)
        )
        return (center[0] - target[0]) ** 2 + (center[1] - target[1]) ** 2

    return (min if face_toward else max)(horizontal, key=distance)


def _gap(left: tuple[float, float], right: tuple[float, float]) -> float:
    return max(0.0, max(left[0], right[0]) - min(left[1], right[1]))


def _overlap_ratio(left: tuple[float, float], right: tuple[float, float]) -> float:
    overlap = max(0.0, min(left[1], right[1]) - max(left[0], right[0]))
    return overlap / min(left[1] - left[0], right[1] - right[0])


def _roof_groups(
    sheds: list[SceneElement], mode: str, gap_tolerance: float
) -> list[list[SceneElement]]:
    if mode == "per_element":
        return [[shed] for shed in sheds]
    remaining = set(range(len(sheds)))
    groups: list[list[SceneElement]] = []
    while remaining:
        stack = [remaining.pop()]
        component: list[int] = []
        while stack:
            current = stack.pop()
            component.append(current)
            current_box = sheds[current].bounding_box
            for candidate in tuple(remaining):
                candidate_box = sheds[candidate].bounding_box
                x_current = (current_box.minimum[0], current_box.maximum[0])
                x_candidate = (candidate_box.minimum[0], candidate_box.maximum[0])
                y_current = (current_box.minimum[1], current_box.maximum[1])
                y_candidate = (candidate_box.minimum[1], candidate_box.maximum[1])
                same_row = (
                    _overlap_ratio(y_current, y_candidate) >= 0.8
                    and _gap(x_current, x_candidate) <= gap_tolerance
                )
                same_column = (
                    _overlap_ratio(x_current, x_candidate) >= 0.8
                    and _gap(y_current, y_candidate) <= gap_tolerance
                )
                if same_row or same_column:
                    remaining.remove(candidate)
                    stack.append(candidate)
        groups.append([sheds[index] for index in component])
    return sorted(
        groups,
        key=lambda group: (
            min(item.bounding_box.minimum[1] for item in group),
            min(item.bounding_box.minimum[0] for item in group),
        ),
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
            or element.semantic_role is SemanticRole.UTILITY_BLOCK
        }
        requested_ids = set(brief.focus_building_ids) | set(brief.context_building_ids)
        if missing := requested_ids - buildable_ids:
            raise ValueError(f"design brief references unknown building IDs: {sorted(missing)}")
        buildings: list[BuildingDesign] = []
        campus_center = _campus_center(scene)
        sheds = [item for item in scene.elements if item.semantic_role is SemanticRole.MAIN_SHED]
        offices = [
            item for item in scene.elements if item.semantic_role is SemanticRole.OFFICE_BLOCK
        ]
        logistics_zones = [
            item
            for item in scene.elements
            if item.semantic_role in {SemanticRole.LOADING_ZONE, SemanticRole.SERVICE_YARD}
        ]
        for element in scene.elements:
            surfaces = _element_surfaces(scene, element)
            if not surfaces and element.semantic_role is not SemanticRole.UTILITY_BLOCK:
                continue
            if element.scene_element_id in brief.context_building_ids:
                treatment = BuildingTreatment.CONTEXT
            elif element.scene_element_id in brief.focus_building_ids or (
                not brief.focus_building_ids
                and element.semantic_role in {SemanticRole.MAIN_SHED, SemanticRole.OFFICE_BLOCK}
            ):
                treatment = BuildingTreatment.FOCUS
            elif element.semantic_role is SemanticRole.UTILITY_BLOCK:
                treatment = BuildingTreatment.AUXILIARY
            elif brief.focus_building_ids:
                treatment = BuildingTreatment.CONTEXT
            else:
                # Authored utility/support masses are part of the subject site, but they must
                # neither receive the shed facade grammar nor become translucent context.
                treatment = BuildingTreatment.AUXILIARY
            peers = offices if element.semantic_role is SemanticRole.MAIN_SHED else sheds
            nearest_peer = (
                min(
                    peers,
                    key=lambda peer: sum(
                        (left - right) ** 2
                        for left, right in zip(
                            _element_center(element), _element_center(peer), strict=True
                        )
                    ),
                )
                if peers
                else None
            )
            nearest_logistics = (
                min(
                    logistics_zones,
                    key=lambda zone: sum(
                        (left - right) ** 2
                        for left, right in zip(
                            _element_center(element), _element_center(zone), strict=True
                        )
                    ),
                )
                if element.semantic_role is SemanticRole.MAIN_SHED
                and brief.loading_docks_per_main_facade
                and logistics_zones
                else None
            )
            front_target = (
                _element_center(nearest_logistics)
                if nearest_logistics is not None
                else _element_center(nearest_peer)
                if nearest_peer
                else campus_center
            )
            front_surface = _front_surface(
                surfaces,
                front_target,
                face_toward=element.semantic_role is not SemanticRole.OFFICE_BLOCK,
            )
            facades = tuple(
                FacadeDesign(
                    surface_id=surface.surface_id,
                    panel_module_m=brief.panel_module_m,
                    office_entrance=(
                        Entrance(
                            u=(0.1 if element.semantic_role is SemanticRole.MAIN_SHED else 0.5),
                            width_m=min(2.4, surface.width_m * 0.25),
                        )
                        if brief.add_office_entrances
                        and (
                            element.semantic_role is SemanticRole.OFFICE_BLOCK
                            or (element.semantic_role is SemanticRole.MAIN_SHED and not offices)
                        )
                        and front_surface is not None
                        and surface.surface_id == front_surface.surface_id
                        else None
                    ),
                    loading_docks=(
                        _loading_docks(surface, brief.loading_docks_per_main_facade)
                        if element.semantic_role is SemanticRole.MAIN_SHED
                        and front_surface is not None
                        and surface.surface_id == front_surface.surface_id
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
        roof_design = RoofDesign(
            roof_type=brief.roof_type,
            solar_panels=brief.solar_panels,
            slope_deg=brief.roof_slope_deg,
            eave_overhang_m=brief.roof_eave_overhang_m,
            ridge_orientation=brief.roof_ridge_orientation,
        )
        focus_sheds = [
            element
            for element in scene.elements
            if element.semantic_role is SemanticRole.MAIN_SHED
            and any(
                building.building_id == element.scene_element_id
                and building.treatment is BuildingTreatment.FOCUS
                for building in buildings
            )
        ]
        roof_assemblies = tuple(
            RoofAssembly(
                assembly_id=f"roof-assembly-{index:02d}",
                building_ids=tuple(
                    item.scene_element_id
                    for item in sorted(group, key=lambda item: item.scene_element_id)
                ),
                bounding_box=BoundingBox(
                    minimum=(
                        min(item.bounding_box.minimum[0] for item in group),
                        min(item.bounding_box.minimum[1] for item in group),
                        min(item.bounding_box.minimum[2] for item in group),
                    ),
                    maximum=(
                        max(item.bounding_box.maximum[0] for item in group),
                        max(item.bounding_box.maximum[1] for item in group),
                        max(item.bounding_box.maximum[2] for item in group),
                    ),
                ),
                roof=roof_design,
            )
            for index, group in enumerate(
                _roof_groups(
                    focus_sheds,
                    brief.roof_grouping_mode,
                    brief.roof_group_gap_tolerance_m,
                ),
                start=1,
            )
        )
        design = DesignDNA(
            project_id=brief.project_id,
            design_revision=design_revision,
            design_language=brief.design_language,
            environment=brief.environment,
            material_palette=brief.material_palette,
            presentation=brief.presentation,
            site_design=brief.site_design,
            industrial_context=PlanIndustrialContext().execute(
                scene, design_revision, brief.site_design
            ),
            design_preferences=brief.design_preferences,
            buildings=tuple(buildings),
            roof_assemblies=roof_assemblies,
            grammar_version=brief.grammar_version,
            asset_library_version=brief.asset_library_version,
        )
        output = scene_path.parent / "designs" / design_revision / "design_dna.json"
        atomic_write(output, design.model_dump_json(indent=2).encode() + b"\n")
        return design
