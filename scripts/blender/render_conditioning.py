"""Build one shared Blender scene and render all persisted cameras.

Executed by Blender, not the control-plane Python environment.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from pathlib import Path

import bpy
import numpy as np
from mathutils import Vector


def arguments() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--scene", type=Path, required=True)
    parser.add_argument("--view-set", type=Path, required=True)
    parser.add_argument("--design-dna", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--width", type=int, default=768)
    parser.add_argument("--height", type=int, default=432)
    parser.add_argument("--view-id", action="append", dest="view_ids")
    parser.add_argument("--pbr-only", action="store_true")
    return parser.parse_args(argv)


def material(
    name: str,
    color: tuple[float, float, float, float],
    metallic: float,
    roughness: float,
):
    value = bpy.data.materials.new(name)
    value.diffuse_color = color
    value.use_nodes = True
    principled = value.node_tree.nodes.get("Principled BSDF")
    principled.inputs["Base Color"].default_value = color
    principled.inputs["Metallic"].default_value = metallic
    principled.inputs["Roughness"].default_value = roughness
    if "Alpha" in principled.inputs:
        principled.inputs["Alpha"].default_value = color[3]
    if color[3] < 1.0:
        if hasattr(value, "surface_render_method"):
            value.surface_render_method = "DITHERED"
        elif hasattr(value, "blend_method"):
            value.blend_method = "BLEND"
        if hasattr(value, "use_transparency_overlap"):
            value.use_transparency_overlap = False
    return value


def emission_material(name: str, color: tuple[float, float, float, float]):
    value = bpy.data.materials.new(name)
    value.diffuse_color = color
    value.use_nodes = True
    nodes = value.node_tree.nodes
    nodes.clear()
    output = nodes.new("ShaderNodeOutputMaterial")
    emission = nodes.new("ShaderNodeEmission")
    emission.inputs["Color"].default_value = color
    emission.inputs["Strength"].default_value = 1.0
    value.node_tree.links.new(emission.outputs["Emission"], output.inputs["Surface"])
    return value


def _hex_color(value: str) -> tuple[float, float, float, float]:
    normalized = value.lstrip("#")
    rgb = tuple(int(normalized[index : index + 2], 16) / 255 for index in (0, 2, 4))
    return (*rgb, 1.0)


def _palette(design_data: dict | None) -> dict[str, str]:
    defaults = {
        "primary_hex": "#E7E5DF",
        "secondary_hex": "#252B31",
        "glass_hex": "#315263",
        "accent_hex": "#2F6B4F",
        "paving_hex": "#777B7A",
    }
    if design_data:
        defaults.update(design_data.get("material_palette", {}))
    return defaults


def build_materials(design_data: dict | None):
    palette = _palette(design_data)
    context_opacity = (
        design_data.get("site_design", {}).get("context_opacity", 0.28) if design_data else 0.28
    )
    return {
        "main_shed": material("main_shed", _hex_color(palette["primary_hex"]), 0.35, 0.3),
        "office_block": material("office_block", _hex_color(palette["primary_hex"]), 0.18, 0.38),
        "service_yard": material("service_yard", _hex_color(palette["paving_hex"]), 0.0, 0.72),
        "site_road": material("site_road", (0.12, 0.135, 0.14, 1), 0.0, 0.82),
        "sidewalk": material("sidewalk", (0.48, 0.49, 0.48, 1), 0.0, 0.76),
        "parking": material("parking", (0.28, 0.30, 0.31, 1), 0.0, 0.8),
        "landscape_zone": material("landscape_zone", (0.10, 0.28, 0.105, 1), 0.0, 0.92),
        "main_entrance": material(
            "main_entrance", _hex_color(palette["secondary_hex"]), 0.25, 0.42
        ),
        "secondary_entrance": material(
            "secondary_entrance", _hex_color(palette["secondary_hex"]), 0.25, 0.42
        ),
        "site_boundary": material("site_boundary", (0.22, 0.24, 0.24, 1), 0.15, 0.55),
        "loading_zone": material("loading_zone", _hex_color(palette["paving_hex"]), 0.0, 0.75),
        "roof": material("roof", (0.62, 0.66, 0.68, 1), 0.48, 0.28),
        "primary_facade": material("primary_facade", _hex_color(palette["primary_hex"]), 0.35, 0.3),
        "context": material("context", (0.66, 0.70, 0.73, context_opacity), 0.05, 0.65),
        "context_landscape": material("context_landscape", (0.12, 0.22, 0.12, 0.72), 0.0, 0.95),
        "utility_block": material("utility_block", _hex_color(palette["secondary_hex"]), 0.2, 0.45),
        "unknown": material("unknown", (0.45, 0.47, 0.48, 1), 0.0, 0.55),
    }


def _roof_rise(bounding_box: dict, roof: dict) -> float:
    minimum = bounding_box["minimum"]
    maximum = bounding_box["maximum"]
    span_x = maximum[0] - minimum[0]
    span_y = maximum[1] - minimum[1]
    long_axis = "x" if span_x >= span_y else "y"
    if roof.get("ridge_orientation", "long_axis") == "short_axis":
        long_axis = "y" if long_axis == "x" else "x"
    cross_span = span_y if long_axis == "x" else span_x
    return min(4.5, max(0.35, cross_span * 0.5 * np.tan(np.radians(roof["slope_deg"]))))


def create_objects(scene_data: dict, scene_root: Path, design_data: dict | None) -> int:
    materials = build_materials(design_data)
    treatments = {
        building["building_id"]: building.get("treatment", "focus")
        for building in (design_data or {}).get("buildings", [])
    }
    roofs = {
        building["building_id"]: building["roof"]
        for building in (design_data or {}).get("buildings", [])
    }
    roof_bounds = {
        building_id: assembly["bounding_box"]
        for assembly in (design_data or {}).get("roof_assemblies", [])
        for building_id in assembly["building_ids"]
    }
    assembly_roofs = {
        building_id: assembly["roof"]
        for assembly in (design_data or {}).get("roof_assemblies", [])
        for building_id in assembly["building_ids"]
    }
    for index, element in enumerate(scene_data["elements"], start=1):
        arrays = np.load(scene_root / element["mesh_ref"])
        vertices = arrays["vertices"].tolist()
        roof = assembly_roofs.get(
            element["scene_element_id"], roofs.get(element["scene_element_id"])
        )
        if (
            roof
            and treatments.get(element["scene_element_id"]) == "focus"
            and element["semantic_role"] == "main_shed"
            and "gable" in roof["roof_type"].casefold()
        ):
            top = element["bounding_box"]["maximum"][2]
            eave = top - _roof_rise(
                roof_bounds.get(element["scene_element_id"], element["bounding_box"]), roof
            )
            vertices = [
                [vertex[0], vertex[1], eave if abs(vertex[2] - top) < 1e-4 else vertex[2]]
                for vertex in vertices
            ]
        faces = arrays["faces"].tolist()
        mesh = bpy.data.meshes.new(element["scene_element_id"])
        mesh.from_pydata(vertices, [], faces)
        mesh.update()
        obj = bpy.data.objects.new(element["scene_element_id"], mesh)
        obj.pass_index = index
        obj["source_external_id"] = element["source"]["external_id"]
        treatment = treatments.get(element["scene_element_id"], "site")
        obj["semantic_role"] = (
            "context_building" if treatment == "context" else element["semantic_role"]
        )
        obj["building_treatment"] = treatment
        selected_material = (
            materials["context"]
            if treatments.get(element["scene_element_id"]) == "context"
            else materials.get(element["semantic_role"], materials["unknown"])
        )
        obj.data.materials.append(selected_material)
        bpy.context.collection.objects.link(obj)
    return len(scene_data["elements"])


def _detail_box(
    name: str,
    surface: dict,
    u_center: float,
    z_center: float,
    width: float,
    height: float,
    depth: float,
    detail_material,
    pass_index: int,
) -> None:
    frame = surface["frame"]
    origin = Vector(frame["origin"])
    u_axis = Vector(frame["u_axis"])
    v_axis = Vector(frame["v_axis"])
    normal = Vector(frame["normal"])
    center = origin + u_axis * u_center + v_axis * z_center + normal * (depth / 2 + 0.03)
    _oriented_box(
        name,
        center,
        ((u_axis, width), (v_axis, height), (normal, depth)),
        detail_material,
        pass_index,
    )


def _oriented_box(
    name: str,
    center: Vector,
    axes_and_sizes: tuple,
    detail_material,
    pass_index: int,
    semantic_role: str = "design_detail",
) -> None:
    first_axis, first_size = axes_and_sizes[0]
    second_axis, second_size = axes_and_sizes[1]
    third_axis, third_size = axes_and_sizes[2]
    vertices = []
    for first_sign, second_sign, third_sign in (
        (-1, -1, -1),
        (1, -1, -1),
        (1, 1, -1),
        (-1, 1, -1),
        (-1, -1, 1),
        (1, -1, 1),
        (1, 1, 1),
        (-1, 1, 1),
    ):
        point = (
            center
            + first_axis * (first_sign * first_size / 2)
            + second_axis * (second_sign * second_size / 2)
            + third_axis * (third_sign * third_size / 2)
        )
        vertices.append(tuple(point))
    faces = (
        (0, 1, 2, 3),
        (4, 7, 6, 5),
        (0, 4, 5, 1),
        (1, 5, 6, 2),
        (2, 6, 7, 3),
        (4, 0, 3, 7),
    )
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    obj.pass_index = pass_index
    obj["semantic_role"] = semantic_role
    obj.data.materials.append(detail_material)
    bpy.context.collection.objects.link(obj)


def _gable_roof(
    name: str,
    bounding_box: dict,
    roof: dict,
    roof_material,
    pass_index: int,
) -> None:
    minimum = bounding_box["minimum"]
    maximum = bounding_box["maximum"]
    x0, y0, _ = minimum
    x1, y1, z_ridge = maximum
    overhang = roof.get("eave_overhang_m", 0.6)
    x0 -= overhang
    x1 += overhang
    y0 -= overhang
    y1 += overhang
    long_axis = "x" if (x1 - x0) >= (y1 - y0) else "y"
    if roof.get("ridge_orientation", "long_axis") == "short_axis":
        long_axis = "y" if long_axis == "x" else "x"
    z_eave = z_ridge - _roof_rise(bounding_box, roof)
    if long_axis == "x":
        middle = (y0 + y1) / 2
        vertices = (
            (x0, y0, z_eave),
            (x1, y0, z_eave),
            (x1, y1, z_eave),
            (x0, y1, z_eave),
            (x0, middle, z_ridge),
            (x1, middle, z_ridge),
        )
    else:
        middle = (x0 + x1) / 2
        vertices = (
            (x0, y0, z_eave),
            (x1, y0, z_eave),
            (x1, y1, z_eave),
            (x0, y1, z_eave),
            (middle, y0, z_ridge),
            (middle, y1, z_ridge),
        )
    faces = (
        (
            (0, 3, 2, 1),
            (0, 1, 5, 4),
            (3, 4, 5, 2),
            (0, 4, 3),
            (1, 2, 5),
        )
        if long_axis == "x"
        else (
            (0, 3, 2, 1),
            (0, 4, 5, 3),
            (1, 2, 5, 4),
            (0, 1, 4),
            (3, 5, 2),
        )
    )
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    obj.pass_index = pass_index
    obj["semantic_role"] = "roof"
    obj["building_treatment"] = "focus"
    obj.data.materials.append(roof_material)
    bpy.context.collection.objects.link(obj)


def create_context_environment(scene_data: dict, design_data: dict, start_index: int) -> int:
    site = design_data.get("site_design", {})
    if site.get("surrounding_context_mode") != "procedural_perimeter":
        return start_index
    elements = scene_data["elements"]
    minimum = [min(item["bounding_box"]["minimum"][axis] for item in elements) for axis in range(3)]
    maximum = [max(item["bounding_box"]["maximum"][axis] for item in elements) for axis in range(3)]
    span_x = maximum[0] - minimum[0]
    span_y = maximum[1] - minimum[1]
    center_x = (minimum[0] + maximum[0]) / 2
    center_y = (minimum[1] + maximum[1]) / 2
    buffer = max(24.0, max(span_x, span_y) * 0.11)
    materials = build_materials(design_data)
    index = start_index

    if site.get("surrounding_landscape_buffer", False):
        strips = (
            (
                Vector((center_x, maximum[1] + buffer / 2, minimum[2] - 0.12)),
                span_x + 2 * buffer,
                buffer,
            ),
            (
                Vector((center_x, minimum[1] - buffer / 2, minimum[2] - 0.12)),
                span_x + 2 * buffer,
                buffer,
            ),
            (Vector((maximum[0] + buffer / 2, center_y, minimum[2] - 0.12)), buffer, span_y),
            (Vector((minimum[0] - buffer / 2, center_y, minimum[2] - 0.12)), buffer, span_y),
        )
        for strip_number, (center, width, depth) in enumerate(strips, start=1):
            index += 1
            _oriented_box(
                f"context-landscape-{strip_number:02d}",
                center,
                ((Vector((1, 0, 0)), width), (Vector((0, 1, 0)), depth), (Vector((0, 0, 1)), 0.2)),
                materials["context_landscape"],
                index,
                semantic_role="context_landscape",
            )

    long_size = max(52.0, min(96.0, span_x * 0.22))
    short_size = max(24.0, min(42.0, span_y * 0.18))
    height = max(7.0, min(11.0, (maximum[2] - minimum[2]) * 0.85))
    slots = (
        (center_x - span_x * 0.28, maximum[1] + buffer * 2.8, long_size, short_size),
        (center_x + span_x * 0.28, maximum[1] + buffer * 2.8, long_size, short_size),
        (maximum[0] + buffer * 2.8, center_y - span_y * 0.25, short_size, long_size),
        (maximum[0] + buffer * 2.8, center_y + span_y * 0.25, short_size, long_size),
        (minimum[0] - buffer * 2.8, center_y - span_y * 0.25, short_size, long_size),
        (minimum[0] - buffer * 2.8, center_y + span_y * 0.25, short_size, long_size),
    )
    count = min(site.get("surrounding_context_count", 0), len(slots))
    for massing_number, (x, y, width, depth) in enumerate(slots[:count], start=1):
        index += 1
        _oriented_box(
            f"procedural-context-{massing_number:02d}",
            Vector((x, y, minimum[2] + height / 2)),
            ((Vector((1, 0, 0)), width), (Vector((0, 1, 0)), depth), (Vector((0, 0, 1)), height)),
            materials["context"],
            index,
            semantic_role="context_building",
        )
    return index


def batch_noncanonical_details(base_object_count: int) -> None:
    """Join generated details by semantic role; their per-object identity is not canonical."""

    for role in ("design_detail", "roof", "context_building", "context_landscape"):
        candidates = [
            obj
            for obj in bpy.context.scene.objects
            if obj.type == "MESH"
            and obj.pass_index > base_object_count
            and obj.get("semantic_role") == role
        ]
        if len(candidates) < 2:
            continue
        bpy.ops.object.select_all(action="DESELECT")
        for obj in candidates:
            obj.select_set(True)
        bpy.context.view_layer.objects.active = candidates[0]
        bpy.ops.object.join()
        merged = candidates[0]
        merged.name = f"batched-{role}"
        merged.pass_index = base_object_count + 1
        merged["semantic_role"] = role


def create_design_details(scene_data: dict, design_data: dict, start_index: int) -> None:
    surfaces = {surface["surface_id"]: surface for surface in scene_data["surfaces"]}
    elements = {element["scene_element_id"]: element for element in scene_data["elements"]}
    has_roof_assemblies = bool(design_data.get("roof_assemblies"))
    assembly_by_building = {
        building_id: assembly
        for assembly in design_data.get("roof_assemblies", [])
        for building_id in assembly["building_ids"]
    }
    palette = _palette(design_data)
    detail_materials = {
        "seam": material("panel_seam", _hex_color(palette["secondary_hex"]), 0.55, 0.32),
        "dock": material("loading_dock", (0.035, 0.045, 0.05, 1), 0.25, 0.42),
        "glass": material("office_glass", _hex_color(palette["glass_hex"]), 0.35, 0.12),
        "accent": material("facade_accent", _hex_color(palette["accent_hex"]), 0.15, 0.3),
        "secondary": material("facade_secondary", _hex_color(palette["secondary_hex"]), 0.4, 0.3),
        "roof": material("designed_roof", (0.62, 0.66, 0.68, 1), 0.48, 0.28),
    }
    detail_index = start_index
    for building in design_data["buildings"]:
        if building.get("treatment", "focus") != "focus":
            continue
        assembly = assembly_by_building.get(building["building_id"])
        for facade in building["facades"]:
            surface = surfaces[facade["surface_id"]]
            if assembly and not _surface_on_assembly_perimeter(surface, assembly["bounding_box"]):
                continue
            width = surface["width_m"]
            height = surface["height_m"]
            if assembly:
                eave = assembly["bounding_box"]["maximum"][2] - _roof_rise(
                    assembly["bounding_box"], assembly["roof"]
                )
                height = min(height, eave - surface["frame"]["origin"][2])
            module = facade["panel_module_m"]
            articulation = facade.get("articulation", {})
            plinth_height = min(articulation.get("plinth_height_m", 0.75), height * 0.22)
            parapet_height = min(articulation.get("parapet_band_height_m", 0.55), height * 0.16)
            for band_name, z_center, band_height in (
                ("plinth", plinth_height / 2, plinth_height),
                ("parapet-band", height - parapet_height / 2, parapet_height),
            ):
                if band_height <= 0:
                    continue
                detail_index += 1
                _detail_box(
                    f"{facade['surface_id']}:{band_name}",
                    surface,
                    width / 2,
                    z_center,
                    width * 0.995,
                    band_height,
                    0.1,
                    detail_materials["secondary"],
                    detail_index,
                )
            seam_count = int(width // module)
            for seam_number in range(1, seam_count + 1):
                detail_index += 1
                _detail_box(
                    f"{facade['surface_id']}:seam-{seam_number:03d}",
                    surface,
                    min(seam_number * module, width - 0.03),
                    height / 2,
                    0.035,
                    height * 0.96,
                    0.06,
                    detail_materials["seam"],
                    detail_index,
                )
            accent_interval = articulation.get("accent_bay_interval", 0)
            if accent_interval:
                for seam_number in range(accent_interval, seam_count, accent_interval):
                    detail_index += 1
                    _detail_box(
                        f"{facade['surface_id']}:accent-bay-{seam_number:03d}",
                        surface,
                        min(seam_number * module, width - module / 2),
                        height / 2,
                        min(module * 0.45, 0.65),
                        max(0.5, height - plinth_height - parapet_height),
                        0.11,
                        detail_materials["accent"],
                        detail_index,
                    )
            for dock in facade["loading_docks"]:
                detail_index += 1
                _detail_box(
                    dock["dock_id"],
                    surface,
                    dock["u"] * width,
                    2.25,
                    dock["width_m"],
                    4.5,
                    0.16,
                    detail_materials["dock"],
                    detail_index,
                )
            entrance = facade.get("office_entrance")
            if entrance:
                glazing_ratio = articulation.get("office_glazing_ratio", 0.72)
                glazing_width = width * glazing_ratio
                glazing_height = max(3.2, height * 0.78)
                glazing_center_z = glazing_height / 2
                frame_depth = articulation.get("feature_frame_depth_m", 0.55)
                detail_index += 1
                _detail_box(
                    f"{facade['surface_id']}:glass-band",
                    surface,
                    width / 2,
                    glazing_center_z,
                    glazing_width,
                    glazing_height,
                    0.12,
                    detail_materials["glass"],
                    detail_index,
                )
                detail_index += 1
                _detail_box(
                    f"{facade['surface_id']}:entrance",
                    surface,
                    entrance["u"] * width,
                    1.5,
                    entrance["width_m"],
                    3.0,
                    0.2,
                    detail_materials["glass"],
                    detail_index,
                )
                frame_width = min(0.38, max(0.18, width * 0.025))
                for side, u_center in (
                    ("left", (width - glazing_width) / 2),
                    ("right", (width + glazing_width) / 2),
                ):
                    detail_index += 1
                    _detail_box(
                        f"{facade['surface_id']}:feature-frame-{side}",
                        surface,
                        u_center,
                        glazing_center_z,
                        frame_width,
                        glazing_height,
                        frame_depth,
                        detail_materials["secondary"],
                        detail_index,
                    )
                detail_index += 1
                _detail_box(
                    f"{facade['surface_id']}:feature-frame-top",
                    surface,
                    width / 2,
                    min(height - frame_width / 2, glazing_height),
                    glazing_width,
                    frame_width,
                    frame_depth,
                    detail_materials["secondary"],
                    detail_index,
                )
                fin_count = articulation.get("vertical_fin_count", 4)
                for fin_number in range(1, fin_count + 1):
                    detail_index += 1
                    _detail_box(
                        f"{facade['surface_id']}:accent-fin-{fin_number:02d}",
                        surface,
                        (width - glazing_width) / 2 + glazing_width * fin_number / (fin_count + 1),
                        glazing_center_z,
                        min(0.18, module * 0.14),
                        glazing_height * 0.94,
                        frame_depth * 1.1,
                        detail_materials["accent"],
                        detail_index,
                    )
                canopy_projection = articulation.get("entrance_canopy_projection_m", 1.8)
                if canopy_projection > 0:
                    frame = surface["frame"]
                    origin = Vector(frame["origin"])
                    u_axis = Vector(frame["u_axis"])
                    v_axis = Vector(frame["v_axis"])
                    normal = Vector(frame["normal"])
                    canopy_width = min(glazing_width * 0.55, entrance["width_m"] * 2.6)
                    canopy_height = min(3.6, height * 0.5)
                    center = (
                        origin
                        + u_axis * (entrance["u"] * width)
                        + v_axis * canopy_height
                        + normal * (canopy_projection / 2 + 0.15)
                    )
                    detail_index += 1
                    _oriented_box(
                        f"{facade['surface_id']}:entrance-canopy",
                        center,
                        (
                            (u_axis, canopy_width),
                            (normal, canopy_projection),
                            (v_axis, 0.24),
                        ),
                        detail_materials["secondary"],
                        detail_index,
                    )
        element = elements[building["building_id"]]
        roof = building["roof"]
        if (
            not has_roof_assemblies
            and element["semantic_role"] == "main_shed"
            and "gable" in roof["roof_type"].casefold()
        ):
            detail_index += 1
            _gable_roof(
                f"{building['building_id']}:gable-roof",
                element["bounding_box"],
                roof,
                detail_materials["roof"],
                detail_index,
            )
    for assembly in design_data.get("roof_assemblies", []):
        roof = assembly["roof"]
        if "gable" not in roof["roof_type"].casefold():
            continue
        detail_index += 1
        _gable_roof(
            assembly["assembly_id"],
            assembly["bounding_box"],
            roof,
            detail_materials["roof"],
            detail_index,
        )


def _surface_on_assembly_perimeter(surface: dict, bounding_box: dict) -> bool:
    normal = surface["frame"]["normal"]
    origin = surface["frame"]["origin"]
    tolerance = 0.02
    if abs(normal[0]) > 0.9:
        boundary = bounding_box["maximum"][0] if normal[0] > 0 else bounding_box["minimum"][0]
        return abs(origin[0] - boundary) <= tolerance
    if abs(normal[1]) > 0.9:
        boundary = bounding_box["maximum"][1] if normal[1] > 0 else bounding_box["minimum"][1]
        return abs(origin[1] - boundary) <= tolerance
    return True


def configure_world(width: int, height: int, design_data: dict | None = None) -> None:
    scene = bpy.context.scene
    try:
        scene.render.engine = "BLENDER_EEVEE_NEXT"
    except TypeError:
        scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = width
    scene.render.resolution_y = height
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"
    scene.render.film_transparent = False
    environment = design_data.get("environment", {}) if design_data else {}
    sun_azimuth = math.radians(float(environment.get("sun_azimuth_deg", 135.0)))
    sun_elevation = math.radians(float(environment.get("sun_elevation_deg", 42.0)))
    scene.world.use_nodes = True
    world_tree = scene.world.node_tree
    world_tree.nodes.clear()
    sky = world_tree.nodes.new("ShaderNodeTexSky")
    sky.sky_type = "NISHITA"
    sky.sun_rotation = sun_azimuth
    sky.sun_elevation = sun_elevation
    sky.air_density = 1.1
    sky.dust_density = 1.4
    sky.ozone_density = 1.0
    background = world_tree.nodes.new("ShaderNodeBackground")
    background.inputs["Strength"].default_value = 0.45
    output = world_tree.nodes.new("ShaderNodeOutputWorld")
    world_tree.links.new(sky.outputs["Color"], background.inputs["Color"])
    world_tree.links.new(background.outputs["Background"], output.inputs["Surface"])
    try:
        scene.view_settings.view_transform = "AgX"
    except TypeError:
        scene.view_settings.view_transform = "Filmic"
    try:
        scene.view_settings.look = "AgX - Medium High Contrast"
    except TypeError:
        scene.view_settings.look = "Medium High Contrast"

    sun_data = bpy.data.lights.new("Sun", type="SUN")
    sun_data.energy = 2.2
    sun_data.angle = math.radians(1.2)
    sun = bpy.data.objects.new("Sun", sun_data)
    sun.rotation_euler = (math.pi / 2 - sun_elevation, 0.0, sun_azimuth)
    bpy.context.collection.objects.link(sun)


def configure_camera(spec: dict):
    data = bpy.data.cameras.new(spec["view_id"])
    data.lens = spec["focal_length_mm"]
    data.sensor_width = spec["sensor_width_mm"]
    data.clip_start = 0.1
    data.clip_end = 5000.0
    camera = bpy.data.objects.new(spec["view_id"], data)
    camera.location = spec["position"]
    direction = Vector(spec["target"]) - camera.location
    camera.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    bpy.context.collection.objects.link(camera)
    bpy.context.scene.camera = camera
    return camera


def file_output(tree, source, socket_name: str, directory: Path, prefix: str, file_format: str):
    node = tree.nodes.new("CompositorNodeOutputFile")
    node.base_path = str(directory)
    node.file_slots[0].path = prefix
    node.format.file_format = file_format
    node.format.color_mode = "RGB"
    socket = next((output for output in source.outputs if output.name == socket_name), None)
    if socket is None:
        available = ", ".join(output.name for output in source.outputs)
        raise RuntimeError(f"missing compositor pass {socket_name}; available: {available}")
    tree.links.new(socket, node.inputs[0])


def render_pbr(view_dir: Path) -> None:
    scene = bpy.context.scene
    layer = scene.view_layers[0]
    layer.use_pass_z = True
    layer.use_pass_normal = True
    scene.use_nodes = True
    tree = scene.node_tree
    tree.nodes.clear()
    render_layers = tree.nodes.new("CompositorNodeRLayers")
    file_output(tree, render_layers, "Depth", view_dir, "depth_", "OPEN_EXR")
    file_output(tree, render_layers, "Normal", view_dir, "normal_", "OPEN_EXR")
    normalized_depth = tree.nodes.new("CompositorNodeNormalize")
    tree.links.new(render_layers.outputs["Depth"], normalized_depth.inputs["Value"])
    file_output(tree, normalized_depth, "Value", view_dir, "depth_preview_", "PNG")
    scene.render.filepath = str(view_dir / "base_rgb.png")
    bpy.ops.render.render(write_still=True)
    for prefix, extension in (
        ("depth_", "exr"),
        ("normal_", "exr"),
        ("depth_preview_", "png"),
    ):
        matches = sorted(view_dir.glob(f"{prefix}*.{extension}"))
        if matches:
            name = "depth.png" if prefix == "depth_preview_" else f"{prefix.rstrip('_')}.exr"
            os.replace(matches[-1], view_dir / name)


def _replace_materials(materials_by_object: dict) -> None:
    for obj, replacement in materials_by_object.items():
        obj.data.materials.clear()
        obj.data.materials.append(replacement)


def render_masks(view_dir: Path) -> None:
    scene = bpy.context.scene
    mesh_objects = [obj for obj in scene.objects if obj.type == "MESH"]
    original = {obj: obj.data.materials[0] for obj in mesh_objects}
    instance_materials = {}
    for obj in mesh_objects:
        value = obj.pass_index
        color = (
            (value & 255) / 255.0,
            ((value >> 8) & 255) / 255.0,
            ((value >> 16) & 255) / 255.0,
            1.0,
        )
        instance_materials[obj] = emission_material(f"id_{value}", color)
    role_colors = {
        "main_shed": (0.85, 0.15, 0.10, 1.0),
        "office_block": (0.10, 0.35, 0.90, 1.0),
        "service_yard": (0.20, 0.70, 0.25, 1.0),
        "site_road": (0.18, 0.18, 0.18, 1.0),
        "sidewalk": (0.55, 0.52, 0.48, 1.0),
        "parking": (0.35, 0.35, 0.35, 1.0),
        "landscape_zone": (0.05, 0.80, 0.12, 1.0),
        "main_entrance": (0.95, 0.10, 0.75, 1.0),
        "secondary_entrance": (0.75, 0.10, 0.55, 1.0),
        "site_boundary": (0.48, 0.25, 0.10, 1.0),
        "loading_zone": (0.20, 0.62, 0.58, 1.0),
        "roof": (0.12, 0.78, 0.82, 1.0),
        "primary_facade": (0.82, 0.42, 0.16, 1.0),
        "context_building": (0.42, 0.46, 0.50, 1.0),
        "context_landscape": (0.08, 0.32, 0.10, 1.0),
        "utility_block": (0.95, 0.65, 0.10, 1.0),
        "unknown": (0.55, 0.55, 0.55, 1.0),
        "design_detail": (0.75, 0.20, 0.85, 1.0),
    }
    semantic_materials = {
        role: emission_material(f"semantic_{role}", color) for role, color in role_colors.items()
    }
    previous_world = scene.world.color[:]
    previous_transform = scene.view_settings.view_transform
    previous_look = scene.view_settings.look
    scene.use_nodes = False
    scene.world.color = (0.0, 0.0, 0.0)
    scene.view_settings.view_transform = "Standard"
    scene.view_settings.look = "Medium High Contrast"
    _replace_materials(instance_materials)
    scene.render.filepath = str(view_dir / "instance_id.png")
    bpy.ops.render.render(write_still=True)
    _replace_materials({obj: semantic_materials[obj["semantic_role"]] for obj in mesh_objects})
    scene.render.filepath = str(view_dir / "semantic.png")
    bpy.ops.render.render(write_still=True)
    _replace_materials(original)
    scene.world.color = previous_world
    scene.view_settings.view_transform = previous_transform
    scene.view_settings.look = previous_look


def render_clay_and_edges(view_dir: Path) -> None:
    scene = bpy.context.scene
    clay = material("clay_override", (0.62, 0.64, 0.66, 1), 0.0, 0.62)
    scene.view_layers[0].material_override = clay
    scene.use_nodes = True
    tree = scene.node_tree
    tree.nodes.clear()
    render_layers = tree.nodes.new("CompositorNodeRLayers")
    sobel = tree.nodes.new("CompositorNodeFilter")
    sobel.filter_type = "SOBEL"
    tree.links.new(render_layers.outputs["Image"], sobel.inputs["Image"])
    edge_output = tree.nodes.new("CompositorNodeOutputFile")
    edge_output.base_path = str(view_dir)
    edge_output.file_slots[0].path = "edges_"
    edge_output.format.file_format = "PNG"
    edge_output.format.color_mode = "BW"
    tree.links.new(sobel.outputs["Image"], edge_output.inputs[0])
    scene.render.filepath = str(view_dir / "clay.png")
    bpy.ops.render.render(write_still=True)
    matches = sorted(view_dir.glob("edges_*.png"))
    if matches:
        os.replace(matches[-1], view_dir / "edges.png")
    scene.view_layers[0].material_override = None


def main() -> None:
    args = arguments()
    scene_path = args.scene.resolve()
    view_set_path = args.view_set.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)

    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    scene_data = json.loads(scene_path.read_text(encoding="utf-8"))
    view_set = json.loads(view_set_path.read_text(encoding="utf-8"))
    design_data = None
    if args.design_dna:
        design_data = json.loads(args.design_dna.resolve().read_text(encoding="utf-8"))
    base_object_count = create_objects(scene_data, scene_path.parent, design_data)
    if design_data:
        detail_start = create_context_environment(scene_data, design_data, base_object_count)
        create_design_details(scene_data, design_data, detail_start)
        batch_noncanonical_details(base_object_count)
    configure_world(args.width, args.height, design_data)
    camera_specs = view_set["cameras"]
    if args.view_ids:
        requested = set(args.view_ids)
        camera_specs = [spec for spec in camera_specs if spec["view_id"] in requested]
        missing = requested - {spec["view_id"] for spec in camera_specs}
        if missing:
            raise ValueError(f"unknown view IDs: {sorted(missing)}")
    for camera_spec in camera_specs:
        view_dir = output / camera_spec["view_id"]
        view_dir.mkdir(parents=True, exist_ok=True)
        (view_dir / "camera.json").write_text(
            json.dumps(camera_spec, indent=2) + "\n", encoding="utf-8"
        )
        camera = configure_camera(camera_spec)
        render_pbr(view_dir)
        if not args.pbr_only:
            render_masks(view_dir)
            render_clay_and_edges(view_dir)
        bpy.data.objects.remove(camera, do_unlink=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(output / "designed_scene.blend"))


main()
