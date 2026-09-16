"""Build one shared Blender scene and render all persisted cameras.

Executed by Blender, not the control-plane Python environment.
"""

from __future__ import annotations

import argparse
import colorsys
import hashlib
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
    parser.add_argument("--asset-library", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--width", type=int)
    parser.add_argument("--height", type=int)
    parser.add_argument(
        "--profile",
        choices=("preview_fast", "standard_eevee", "premium_cycles"),
        default="standard_eevee",
    )
    parser.add_argument("--view-id", action="append", dest="view_ids")
    parser.add_argument("--pbr-only", action="store_true")
    return parser.parse_args(argv)


def material(
    name: str,
    color: tuple[float, float, float, float],
    metallic: float,
    roughness: float,
    micro_surface: dict | None = None,
    optical: dict | None = None,
    texture_files: dict[str, Path] | None = None,
    texture_scale_m: float | None = None,
):
    value = bpy.data.materials.new(name)
    value.diffuse_color = color
    value.use_nodes = True
    principled = value.node_tree.nodes.get("Principled BSDF")
    principled.inputs["Base Color"].default_value = color
    principled.inputs["Metallic"].default_value = metallic
    principled.inputs["Roughness"].default_value = roughness
    _apply_optical_properties(principled, optical or {})
    _add_micro_surface(value, principled, name, roughness, micro_surface)
    if texture_files:
        _add_image_textures(value, principled, texture_files, texture_scale_m or 1.0)
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


def _add_image_textures(
    value,
    principled,
    texture_files: dict[str, Path],
    texture_scale_m: float,
) -> None:
    """Apply real-world-scale PBR maps using stable world-space projection."""

    nodes = value.node_tree.nodes
    links = value.node_tree.links
    geometry = nodes.new("ShaderNodeNewGeometry")
    mapping = nodes.new("ShaderNodeVectorMath")
    mapping.operation = "SCALE"
    mapping.inputs["Scale"].default_value = 1.0 / texture_scale_m
    links.new(geometry.outputs["Position"], mapping.inputs[0])

    def image_node(role: str, *, non_color: bool = False):
        path = texture_files.get(role)
        if path is None:
            return None
        node = nodes.new("ShaderNodeTexImage")
        node.image = bpy.data.images.load(str(path), check_existing=True)
        node.extension = "REPEAT"
        node.projection = "FLAT"
        if non_color:
            node.image.colorspace_settings.name = "Non-Color"
        links.new(mapping.outputs["Vector"], node.inputs["Vector"])
        return node

    albedo = image_node("albedo")
    if albedo is not None:
        links.new(albedo.outputs["Color"], principled.inputs["Base Color"])
    roughness = image_node("roughness", non_color=True)
    if roughness is not None:
        links.new(roughness.outputs["Color"], principled.inputs["Roughness"])
    normal = image_node("normal", non_color=True)
    if normal is not None:
        normal_map = nodes.new("ShaderNodeNormalMap")
        normal_map.inputs["Strength"].default_value = 0.55
        links.new(normal.outputs["Color"], normal_map.inputs["Color"])
        links.new(normal_map.outputs["Normal"], principled.inputs["Normal"])


def _apply_optical_properties(principled, properties: dict) -> None:
    """Set Principled inputs across Blender 4.x naming changes."""

    aliases = {
        "transmission_weight": ("Transmission Weight", "Transmission"),
        "ior": ("IOR",),
        "coat_weight": ("Coat Weight", "Clearcoat"),
        "coat_roughness": ("Coat Roughness", "Clearcoat Roughness"),
    }
    defaults = {
        "transmission_weight": 0.0,
        "ior": 1.5,
        "coat_weight": 0.0,
        "coat_roughness": 0.03,
    }
    for key, names in aliases.items():
        value = float(properties.get(key, defaults[key]))
        socket = next(
            (principled.inputs.get(name) for name in names if principled.inputs.get(name)),
            None,
        )
        if socket is not None:
            socket.default_value = value


def _add_micro_surface(
    value,
    principled,
    name: str,
    roughness: float,
    definition: dict | None = None,
) -> None:
    """Add lightweight world-scale roughness/normal variation without texture memory."""

    profiles = {
        "main_shed": (5.0, 0.055, 0.08),
        "office_block": (4.0, 0.04, 0.055),
        "primary_facade": (5.0, 0.055, 0.08),
        "roof": (7.0, 0.045, 0.07),
        "service_yard": (2.4, 0.10, 0.16),
        "loading_zone": (2.4, 0.10, 0.16),
        "sidewalk": (3.2, 0.085, 0.13),
        "parking": (2.0, 0.105, 0.18),
        "site_road": (1.8, 0.11, 0.20),
    }
    profile = (
        (
            definition["scale_per_m"],
            definition["roughness_variation"],
            definition["bump_strength"],
            definition["bump_distance_m"],
        )
        if definition
        else (*profiles[name], 0.035)
        if name in profiles
        else None
    )
    if profile is None:
        return
    scale, roughness_variation, bump_strength, bump_distance = profile
    nodes = value.node_tree.nodes
    links = value.node_tree.links
    geometry = nodes.new("ShaderNodeNewGeometry")
    vector_scale = nodes.new("ShaderNodeVectorMath")
    vector_scale.operation = "SCALE"
    vector_scale.inputs["Scale"].default_value = scale
    noise = nodes.new("ShaderNodeTexNoise")
    noise.noise_dimensions = "3D"
    noise.inputs["Scale"].default_value = 1.0
    noise.inputs["Detail"].default_value = 3.0
    noise.inputs["Roughness"].default_value = 0.58
    ramp = nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].color = (max(0.0, roughness - roughness_variation),) * 3 + (1.0,)
    ramp.color_ramp.elements[1].color = (min(1.0, roughness + roughness_variation),) * 3 + (1.0,)
    bump = nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = bump_strength
    bump.inputs["Distance"].default_value = bump_distance
    links.new(geometry.outputs["Position"], vector_scale.inputs[0])
    links.new(vector_scale.outputs["Vector"], noise.inputs["Vector"])
    links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
    links.new(ramp.outputs["Color"], principled.inputs["Roughness"])
    links.new(noise.outputs["Fac"], bump.inputs["Height"])
    links.new(bump.outputs["Normal"], principled.inputs["Normal"])


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
    encoded = tuple(int(normalized[index : index + 2], 16) / 255 for index in (0, 2, 4))

    def to_linear(channel: float) -> float:
        return channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4

    return (*(to_linear(channel) for channel in encoded), 1.0)


def _linear_channel_to_srgb8(value: float) -> int:
    encoded = 12.92 * value if value <= 0.0031308 else 1.055 * value ** (1 / 2.4) - 0.055
    return round(max(0.0, min(1.0, encoded)) * 255)


def _palette(design_data: dict | None) -> dict[str, str]:
    defaults = {
        "roof_hex": "#E8E7E1",
        "primary_hex": "#E7E5DF",
        "secondary_hex": "#252B31",
        "glass_hex": "#315263",
        "accent_hex": "#2F6B4F",
        "boundary_hex": "#626B70",
        "paving_hex": "#777B7A",
    }
    if design_data:
        defaults.update(design_data.get("material_palette", {}))
    return defaults


def _material_specs(asset_data: dict | None) -> dict[str, dict]:
    specs = {}
    for asset in (asset_data or {}).get("assets", []):
        if asset.get("kind") != "material" or not asset.get("material"):
            continue
        for role in asset.get("semantic_roles", []):
            if role in specs:
                raise ValueError(f"duplicate material asset assignment for semantic role {role}")
            specs[role] = asset
    return specs


def build_materials(
    design_data: dict | None,
    asset_data: dict | None = None,
    asset_root: Path | None = None,
):
    if asset_root is None and asset_data and asset_data.get("_asset_root"):
        asset_root = Path(asset_data["_asset_root"])
    palette = _palette(design_data)
    specs = _material_specs(asset_data)
    requested_context_opacity = (
        design_data.get("site_design", {}).get("context_opacity", 0.46) if design_data else 0.46
    )
    # Context sheds are a planning aid, not part of the proposed architecture. Keep them
    # unmistakably secondary; a separate deterministic overlay preserves this opacity after AI.
    context_opacity = max(0.22, min(0.30, requested_context_opacity))

    def resolved(
        role: str,
        fallback_color: tuple[float, float, float, float],
        fallback_metallic: float,
        fallback_roughness: float,
    ):
        asset = specs.get(role, {})
        asset_id = asset.get("asset_id", f"fallback.{role}")
        spec = asset.get("material", {})
        color_source = spec.get("color_source")
        color = fallback_color
        if isinstance(color_source, str):
            if color_source.startswith("palette:"):
                color = _hex_color(palette[color_source.removeprefix("palette:")])
            elif color_source.startswith("#"):
                color = _hex_color(color_source)
        opacity = float(spec.get("opacity", color[3]))
        texture_files = {
            item["role"]: (asset_root / item["path"]).resolve()
            for item in asset.get("files", [])
            if asset_root is not None
        }
        if role == "site_road":
            # The bundled asphalt scan has useful normal/roughness maps, but its brown, pale
            # albedo reads as concrete in aerial views and overrides the authoritative charcoal
            # road colour. Retain surface response while letting the explicit asphalt colour drive
            # the base channel. Parking is intentionally allowed to keep the lighter scan.
            texture_files.pop("albedo", None)
        result = material(
            role,
            (*color[:3], opacity),
            float(spec.get("metallic", fallback_metallic)),
            float(spec.get("roughness", fallback_roughness)),
            spec.get("micro_surface"),
            spec,
            texture_files,
            spec.get("texture_scale_m"),
        )
        result["asset_id"] = asset_id
        return result

    return {
        "main_shed": resolved("main_shed", _hex_color(palette["primary_hex"]), 0.35, 0.3),
        "office_block": resolved("office_block", _hex_color(palette["primary_hex"]), 0.18, 0.38),
        "service_yard": resolved("service_yard", _hex_color(palette["paving_hex"]), 0.0, 0.72),
        # This is the model's continuous substrate, not a semantic concrete apron.
        # Keep it neutral and subordinate so the overlaid authored site surfaces remain legible.
        "site_ground": material("site_ground", (0.29, 0.31, 0.29, 1.0), 0.0, 0.94),
        "site_road": resolved("site_road", (0.12, 0.135, 0.14, 1), 0.0, 0.82),
        "sidewalk": resolved("sidewalk", (0.48, 0.49, 0.48, 1), 0.0, 0.76),
        "parking": resolved("parking", (0.28, 0.30, 0.31, 1), 0.0, 0.8),
        "landscape_zone": resolved("landscape_zone", (0.10, 0.28, 0.105, 1), 0.0, 0.92),
        "main_entrance": material(
            "main_entrance", _hex_color(palette["secondary_hex"]), 0.25, 0.42
        ),
        "secondary_entrance": material(
            "secondary_entrance", _hex_color(palette["secondary_hex"]), 0.25, 0.42
        ),
        "site_boundary": material("site_boundary", _hex_color(palette["boundary_hex"]), 0.15, 0.55),
        "loading_zone": resolved("loading_zone", _hex_color(palette["paving_hex"]), 0.0, 0.75),
        "roof": resolved("roof", _hex_color(palette["roof_hex"]), 0.48, 0.28),
        "primary_facade": resolved("primary_facade", _hex_color(palette["primary_hex"]), 0.35, 0.3),
        # A restrained frosted proxy keeps neighbouring factories legible but secondary. The
        # minimum opacity retains contact shadows and avoids floating/ghost geometry.
        "context": material("context", (0.76, 0.78, 0.78, context_opacity), 0.0, 0.92),
        "context_landscape": resolved("context_landscape", (0.12, 0.22, 0.12, 0.72), 0.0, 0.95),
        "office_glass": resolved("office_glass", _hex_color(palette["glass_hex"]), 0.08, 0.16),
        "facade_accent": resolved("facade_accent", _hex_color(palette["accent_hex"]), 0.22, 0.34),
        "facade_secondary": resolved(
            "facade_secondary", _hex_color(palette["secondary_hex"]), 0.32, 0.36
        ),
        "loading_dock": resolved("loading_dock", (0.035, 0.045, 0.05, 1), 0.18, 0.48),
        "door_shutter": resolved("door_shutter", (0.50, 0.53, 0.54, 1), 0.34, 0.42),
        "panel_seam": resolved("panel_seam", _hex_color(palette["secondary_hex"]), 0.35, 0.38),
        "tree_foliage": resolved("tree_foliage", (0.075, 0.24, 0.08, 1), 0.0, 0.86),
        "tree_trunk": resolved("tree_trunk", (0.16, 0.085, 0.035, 1), 0.0, 0.82),
        "vehicle_body": resolved("vehicle_body", (0.58, 0.60, 0.59, 1), 0.22, 0.32),
        "vehicle_glass": resolved("vehicle_glass", (0.035, 0.055, 0.065, 1), 0.04, 0.18),
        "vehicle_tire": resolved("vehicle_tire", (0.018, 0.02, 0.022, 1), 0.0, 0.9),
        "person": resolved("person", (0.22, 0.24, 0.23, 1), 0.0, 0.72),
        "utility_block": material("utility_block", (0.32, 0.34, 0.35, 1), 0.12, 0.52),
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


def create_objects(
    scene_data: dict,
    scene_root: Path,
    design_data: dict | None,
    asset_data: dict | None = None,
) -> int:
    materials = build_materials(design_data, asset_data)
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
    semantic_role: str | None = None,
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
        semantic_role=semantic_role,
    )


def _material_semantic_role(detail_material) -> str:
    material_role = detail_material.name.split(".", maxsplit=1)[0]
    return {
        "facade_accent": "brand_accent",
        "office_glass": "glazing",
        "facade_secondary": "facade_secondary",
        "loading_dock": "facade_secondary",
        "door_shutter": "facade_secondary",
        "panel_seam": "facade_secondary",
    }.get(material_role, "design_detail")


def _oriented_box(
    name: str,
    center: Vector,
    axes_and_sizes: tuple,
    detail_material,
    pass_index: int,
    semantic_role: str | None = None,
):
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
    obj["semantic_role"] = semantic_role or _material_semantic_role(detail_material)
    obj.data.materials.append(detail_material)
    bpy.context.collection.objects.link(obj)
    return obj


def _tapered_prism(
    name: str,
    base_center: Vector,
    forward: Vector,
    lateral: Vector,
    length: float,
    width: float,
    height: float,
    top_scale: float,
    detail_material,
    pass_index: int,
    semantic_role: str,
):
    up = Vector((0, 0, 1))
    vertices = []
    for z_offset, scale in ((0.0, 1.0), (height, top_scale)):
        for longitudinal, transverse in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
            point = (
                base_center
                + forward * (longitudinal * length * scale / 2)
                + lateral * (transverse * width * scale / 2)
                + up * z_offset
            )
            vertices.append(tuple(point))
    faces = (
        (0, 1, 2, 3),
        (4, 7, 6, 5),
        (0, 4, 5, 1),
        (1, 5, 6, 2),
        (2, 6, 7, 3),
        (3, 7, 4, 0),
    )
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    obj.pass_index = pass_index
    obj["semantic_role"] = semantic_role
    obj.data.materials.append(detail_material)
    bpy.context.collection.objects.link(obj)
    return obj


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


def create_context_environment(
    scene_data: dict,
    design_data: dict,
    start_index: int,
    asset_data: dict | None = None,
) -> int:
    site = design_data.get("site_design", {})
    context_plan = design_data.get("industrial_context") or {}
    if context_plan.get("mode") == "conceptual_industrial_park":
        materials = build_materials(design_data, asset_data)
        index = start_index

        def add_box(name: str, box: dict, material_value, role: str) -> None:
            nonlocal index
            minimum = box["minimum"]
            maximum = box["maximum"]
            index += 1
            _oriented_box(
                name,
                Vector(tuple((minimum[axis] + maximum[axis]) / 2 for axis in range(3))),
                tuple(
                    (
                        Vector(
                            (1 if axis == 0 else 0, 1 if axis == 1 else 0, 1 if axis == 2 else 0)
                        ),
                        maximum[axis] - minimum[axis],
                    )
                    for axis in range(3)
                ),
                material_value,
                index,
                semantic_role=role,
            )

        if context_plan.get("ground"):
            add_box(
                "conceptual-context-ground",
                context_plan["ground"],
                materials["context_landscape"],
                "context_landscape",
            )
        for road in context_plan.get("roads", []):
            add_box(
                road["road_id"], road["bounding_box"], materials["site_road"], "context_landscape"
            )
        for proxy in context_plan.get("proxy_buildings", []):
            add_box(
                proxy["proxy_id"], proxy["bounding_box"], materials["context"], "context_building"
            )
        return index
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
    materials = build_materials(design_data, asset_data)
    index = start_index

    # Aerial cameras otherwise see the physically empty lower hemisphere of the sky as a black
    # void outside the authored site.  This low-detail receiver gives AI a stable, explicitly
    # non-authoritative context surface while all authored roads and landscape remain above it.
    context_extent = max(max(span_x, span_y) * 6.0, max(span_x, span_y) + buffer * 9.0)
    index += 1
    _oriented_box(
        "procedural-context-ground",
        Vector((center_x, center_y, minimum[2] - 0.32)),
        (
            (Vector((1, 0, 0)), context_extent),
            (Vector((0, 1, 0)), context_extent),
            (Vector((0, 0, 1)), 0.2),
        ),
        materials["context_landscape"],
        index,
        semantic_role="context_landscape",
    )

    # Establish an industrial-estate reading instead of leaving isolated warehouses in an
    # undifferentiated green field. These roads stay outside the authored scene envelope and are
    # non-authoritative context, so they can never replace model-derived circulation.
    road_width = max(9.0, min(16.0, min(span_x, span_y) * 0.035))
    road_offset = buffer * 1.55
    road_length_x = span_x + buffer * 7.2
    road_length_y = span_y + buffer * 7.2
    context_roads = (
        (
            "north",
            Vector((center_x, maximum[1] + road_offset, minimum[2] - 0.04)),
            road_length_x,
            road_width,
        ),
        (
            "south",
            Vector((center_x, minimum[1] - road_offset, minimum[2] - 0.04)),
            road_length_x,
            road_width,
        ),
        (
            "east",
            Vector((maximum[0] + road_offset, center_y, minimum[2] - 0.04)),
            road_width,
            road_length_y,
        ),
        (
            "west",
            Vector((minimum[0] - road_offset, center_y, minimum[2] - 0.04)),
            road_width,
            road_length_y,
        ),
    )
    for road_name, center, width, depth in context_roads:
        index += 1
        _oriented_box(
            f"procedural-context-road-{road_name}",
            center,
            (
                (Vector((1, 0, 0)), width),
                (Vector((0, 1, 0)), depth),
                (Vector((0, 0, 1)), 0.12),
            ),
            materials["site_road"],
            index,
            semantic_role="context_landscape",
        )

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
    # Neighbouring plots are laid out as an estate, not as a single ring of slabs. A ring at one
    # standoff reads from the air as isolated blocks in empty land; two rows on every side, each
    # offset along the frontage, reads as the project sitting on one lot among many.
    slots = tuple(
        slot
        for standoff in (2.6, 5.6)
        for along in (-0.34, 0.0, 0.34)
        for slot in (
            (center_x + along * span_x, maximum[1] + buffer * standoff, long_size, short_size),
            (center_x + along * span_x, minimum[1] - buffer * standoff, long_size, short_size),
            (maximum[0] + buffer * standoff, center_y + along * span_y, short_size, long_size),
            (minimum[0] - buffer * standoff, center_y + along * span_y, short_size, long_size),
        )
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


def _stable_rng(*parts: str):
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).digest()
    return np.random.default_rng(int.from_bytes(digest[:8], "big"))


def _triangle_samples(
    element: dict,
    scene_root: Path,
    count: int,
    seed_parts: tuple[str, ...],
) -> list[tuple[float, float, float]]:
    """Sample an authored horizontal mesh, never its rectangular bounding box."""

    if count <= 0:
        return []
    arrays = np.load(scene_root / element["mesh_ref"])
    vertices = np.asarray(arrays["vertices"], dtype=float)
    triangles = []
    weights = []
    for face in arrays["faces"].tolist():
        if len(face) < 3:
            continue
        for offset in range(1, len(face) - 1):
            triangle = vertices[[face[0], face[offset], face[offset + 1]]]
            first = triangle[1, :2] - triangle[0, :2]
            second = triangle[2, :2] - triangle[0, :2]
            area = abs(first[0] * second[1] - first[1] * second[0]) / 2
            if area > 1e-4:
                triangles.append(triangle)
                weights.append(area)
    if not triangles:
        return []
    rng = _stable_rng(*seed_parts)
    probabilities = np.asarray(weights) / sum(weights)
    results = []
    attempts = max(count * 8, 16)
    while len(results) < count and attempts:
        attempts -= 1
        triangle = triangles[int(rng.choice(len(triangles), p=probabilities))]
        first, second = rng.random(2)
        if first + second > 1:
            first, second = 1 - first, 1 - second
        # Pull the point slightly towards the triangle centroid so trunks do not straddle curbs.
        point = (
            triangle[0] + first * (triangle[1] - triangle[0]) + second * (triangle[2] - triangle[0])
        )
        point = point * 0.86 + triangle.mean(axis=0) * 0.14
        candidate = tuple(float(value) for value in point)
        if all(math.dist(candidate[:2], existing[:2]) >= 3.2 for existing in results):
            results.append(candidate)
    return results


def _tag_asset(obj, instance_id: str, asset_id: str, semantic_role: str, pass_index: int) -> None:
    obj.pass_index = pass_index
    obj["asset_instance_id"] = instance_id
    obj["asset_id"] = asset_id
    obj["semantic_role"] = semantic_role


def _create_tree(
    instance_id: str,
    asset_id: str,
    location: tuple[float, float, float],
    height: float,
    materials: dict,
    pass_index: int,
) -> None:
    x, y, z = location
    trunk_height = height * 0.43
    bpy.ops.mesh.primitive_cylinder_add(
        vertices=8,
        radius=max(0.12, height * 0.028),
        depth=trunk_height,
        location=(x, y, z + trunk_height / 2),
    )
    trunk = bpy.context.object
    trunk.name = f"{instance_id}:trunk"
    trunk.data.materials.append(materials["tree_trunk"])
    _tag_asset(trunk, instance_id, asset_id, "tree", pass_index)
    crown_radius = height * 0.22
    for layer, (radius_factor, z_factor) in enumerate(((1.0, 0.52), (0.82, 0.70)), start=1):
        bpy.ops.mesh.primitive_ico_sphere_add(
            subdivisions=1,
            radius=crown_radius * radius_factor,
            location=(x, y, z + height * z_factor),
        )
        crown = bpy.context.object
        crown.name = f"{instance_id}:crown-{layer}"
        crown.scale.z = 1.18
        crown.data.materials.append(materials["tree_foliage"])
        _tag_asset(crown, instance_id, asset_id, "tree", pass_index)


def _create_vehicle(
    instance_id: str,
    asset_id: str,
    location: tuple[float, float, float],
    dimensions: tuple[float, float, float],
    long_axis: str,
    materials: dict,
    pass_index: int,
) -> None:
    x, y, z = location
    length, width, height = dimensions
    forward = Vector((1, 0, 0)) if long_axis == "x" else Vector((0, 1, 0))
    lateral = Vector((0, 1, 0)) if long_axis == "x" else Vector((1, 0, 0))
    up = Vector((0, 0, 1))
    body = _oriented_box(
        f"{instance_id}:body",
        Vector((x, y, z + height * 0.28)),
        ((forward, length), (lateral, width), (up, height * 0.50)),
        materials["vehicle_body"],
        pass_index,
        semantic_role="vehicle",
    )
    _tag_asset(body, instance_id, asset_id, "vehicle", pass_index)
    cabin = _tapered_prism(
        f"{instance_id}:cabin",
        Vector((x, y, z + height * 0.52)) + forward * (length * 0.06),
        forward,
        lateral,
        length * 0.5,
        width * 0.9,
        height * 0.4,
        0.7,
        materials["vehicle_glass"],
        pass_index,
        "vehicle",
    )
    _tag_asset(cabin, instance_id, asset_id, "vehicle", pass_index)
    for side in (-1, 1):
        for along in (-0.31, 0.31):
            center = Vector((x, y, z + height * 0.18))
            center += forward * (length * along) + lateral * (width * 0.49 * side)
            bpy.ops.mesh.primitive_cylinder_add(
                vertices=10,
                radius=height * 0.18,
                depth=width * 0.10,
                location=center,
                rotation=(math.pi / 2, 0, 0) if long_axis == "x" else (0, math.pi / 2, 0),
            )
            wheel = bpy.context.object
            wheel.name = f"{instance_id}:wheel-{side}-{along}"
            wheel.data.materials.append(materials["vehicle_tire"])
            _tag_asset(wheel, instance_id, asset_id, "vehicle", pass_index)


def _create_person(
    instance_id: str,
    asset_id: str,
    location: Vector,
    materials: dict,
    pass_index: int,
) -> None:
    height = 1.72
    bpy.ops.mesh.primitive_cylinder_add(
        vertices=8,
        radius=0.20,
        depth=height * 0.68,
        location=location + Vector((0, 0, height * 0.34)),
    )
    body = bpy.context.object
    body.name = f"{instance_id}:body"
    body.data.materials.append(materials["person"])
    _tag_asset(body, instance_id, asset_id, "person", pass_index)
    bpy.ops.mesh.primitive_ico_sphere_add(
        subdivisions=1,
        radius=0.16,
        location=location + Vector((0, 0, height * 0.82)),
    )
    head = bpy.context.object
    head.name = f"{instance_id}:head"
    head.data.materials.append(materials["person"])
    _tag_asset(head, instance_id, asset_id, "person", pass_index)


def _geometry_asset(asset_data: dict | None, kind: str, role: str) -> dict | None:
    candidates = [
        asset
        for asset in (asset_data or {}).get("assets", [])
        if asset.get("kind") == kind and role in asset.get("semantic_roles", [])
    ]
    if len(candidates) > 1:
        raise ValueError(f"multiple {kind} assets resolve semantic role {role}")
    return candidates[0] if candidates else None


def create_deterministic_entourage(
    scene_data: dict,
    scene_root: Path,
    design_data: dict,
    start_index: int,
    asset_data: dict | None = None,
) -> tuple[int, list[dict]]:
    """Place lightweight scale cues once in the shared scene, based only on authored semantics."""

    density = design_data.get("presentation", {}).get("entourage_density", "low")
    if density == "none":
        return start_index, []
    density_factor = {"low": 0.65, "medium": 1.0, "high": 1.35}[density]
    revision = str(design_data.get("design_revision", "unversioned"))
    materials = build_materials(design_data, asset_data)
    tree_asset = _geometry_asset(asset_data, "vegetation", "landscape_zone")
    car_asset = _geometry_asset(asset_data, "vehicle", "parking")
    truck_asset = _geometry_asset(asset_data, "vehicle", "service_yard")
    person_asset = _geometry_asset(asset_data, "person", "office_entrance")
    index = start_index
    records = []

    if tree_asset:
        for element in scene_data["elements"]:
            if element["semantic_role"] != "landscape_zone":
                continue
            bounds = element["bounding_box"]
            area = max(0.0, bounds["maximum"][0] - bounds["minimum"][0]) * max(
                0.0, bounds["maximum"][1] - bounds["minimum"][1]
            )
            count = min(10, max(1, round(area / 240 * density_factor)))
            points = _triangle_samples(
                element,
                scene_root,
                count,
                (revision, element["scene_element_id"], tree_asset["asset_id"]),
            )
            rng = _stable_rng(revision, element["scene_element_id"], "tree-scale")
            for ordinal, point in enumerate(points, start=1):
                index += 1
                instance_id = f"tree:{element['scene_element_id']}:{ordinal:02d}"
                height = float(rng.uniform(4.5, 7.2))
                _create_tree(instance_id, tree_asset["asset_id"], point, height, materials, index)
                records.append(
                    {
                        "instance_id": instance_id,
                        "asset_id": tree_asset["asset_id"],
                        "position": point,
                        "height_m": height,
                    }
                )

    if car_asset:
        candidates = [
            element for element in scene_data["elements"] if element["semantic_role"] == "parking"
        ]
        cap = max(1, round(4 * density_factor))
        for element in candidates[:cap]:
            bounds = element["bounding_box"]
            span_x = bounds["maximum"][0] - bounds["minimum"][0]
            span_y = bounds["maximum"][1] - bounds["minimum"][1]
            location = (
                (bounds["minimum"][0] + bounds["maximum"][0]) / 2,
                (bounds["minimum"][1] + bounds["maximum"][1]) / 2,
                bounds["maximum"][2] + 0.03,
            )
            dimensions = tuple(car_asset.get("physical_dimensions_m") or (4.6, 1.85, 1.55))
            index += 1
            instance_id = f"vehicle:{element['scene_element_id']}"
            _create_vehicle(
                instance_id,
                car_asset["asset_id"],
                location,
                dimensions,
                "x" if span_x >= span_y else "y",
                materials,
                index,
            )
            records.append(
                {
                    "instance_id": instance_id,
                    "asset_id": car_asset["asset_id"],
                    "position": location,
                    "dimensions_m": dimensions,
                }
            )

    # Service vehicles are only valid when tied to an authored loading dock. A truck at the
    # centre of a generic yard can obstruct the human camera and invent an operational layout.
    if truck_asset and density == "high":
        surfaces = {surface["surface_id"]: surface for surface in scene_data["surfaces"]}
        docks = [
            (dock, surfaces.get(facade["surface_id"]))
            for building in design_data.get("buildings", [])
            if building.get("treatment", "focus") == "focus"
            for facade in building.get("facades", [])
            for dock in facade.get("loading_docks", [])
        ]
        # Always leave at least one complete logistics bay unobstructed for design review.
        cap = min(max(0, len(docks) - 1), max(1, round(2 * density_factor)))
        dimensions = tuple(truck_asset.get("physical_dimensions_m") or (6.8, 2.35, 2.75))
        # Keep the nearest approach zone legible: the camera planner enters each row from its
        # minimum longitudinal end, so prefer the far authored docks for sparse entourage.
        for dock, surface in docks[-cap:]:
            if not surface:
                continue
            frame = surface["frame"]
            normal = Vector(frame["normal"])
            location_vector = (
                Vector(frame["origin"])
                + Vector(frame["u_axis"]) * (dock["u"] * surface["width_m"])
                + normal * (dimensions[0] / 2 + 0.8)
                + Vector((0, 0, 0.03))
            )
            location = tuple(location_vector)
            index += 1
            instance_id = f"vehicle:{dock['dock_id']}"
            _create_vehicle(
                instance_id,
                truck_asset["asset_id"],
                location,
                dimensions,
                "x" if abs(normal.x) >= abs(normal.y) else "y",
                materials,
                index,
            )
            records.append(
                {
                    "instance_id": instance_id,
                    "asset_id": truck_asset["asset_id"],
                    "position": location,
                    "dimensions_m": dimensions,
                    "source_dock_id": dock["dock_id"],
                }
            )

    if person_asset:
        surfaces = {surface["surface_id"]: surface for surface in scene_data["surfaces"]}
        entrances = [
            (facade, surfaces.get(facade["surface_id"]))
            for building in design_data.get("buildings", [])
            if building.get("treatment", "focus") == "focus"
            for facade in building.get("facades", [])
            if facade.get("office_entrance")
        ]
        cap = max(1, round(4 * density_factor))
        for facade, surface in entrances[:cap]:
            if not surface:
                continue
            frame = surface["frame"]
            entrance = facade["office_entrance"]
            location = (
                Vector(frame["origin"])
                + Vector(frame["u_axis"]) * (entrance["u"] * surface["width_m"])
                + Vector(frame["normal"]) * 1.35
            )
            index += 1
            instance_id = f"person:{facade['surface_id']}"
            _create_person(instance_id, person_asset["asset_id"], location, materials, index)
            records.append(
                {
                    "instance_id": instance_id,
                    "asset_id": person_asset["asset_id"],
                    "position": tuple(location),
                }
            )
    return index, records


def batch_noncanonical_details(base_object_count: int) -> None:
    """Join generated details by semantic role; their per-object identity is not canonical."""

    for role in (
        "design_detail",
        "facade_secondary",
        "glazing",
        "brand_accent",
        "roof",
        "site_boundary",
        "context_building",
        "context_landscape",
    ):
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


def _subtract_intervals(
    whole: tuple[float, float], gaps: list[tuple[float, float]]
) -> list[tuple[float, float]]:
    """Return fence runs after clipping and removing authored entrance openings."""

    start, end = whole
    clipped = sorted(
        (max(start, left), min(end, right)) for left, right in gaps if right > start and left < end
    )
    runs: list[tuple[float, float]] = []
    cursor = start
    for left, right in clipped:
        if left > cursor:
            runs.append((cursor, left))
        cursor = max(cursor, right)
    if cursor < end:
        runs.append((cursor, end))
    return [run for run in runs if run[1] - run[0] >= 0.6]


def _create_site_fence(
    scene_data: dict,
    material,
    start_index: int,
    boundary_kit: str = "preserve_model",
) -> int:
    """Build a model-derived perimeter fence, preserving openings at authored gates."""

    boundaries = [
        item for item in scene_data["elements"] if item["semantic_role"] == "site_boundary"
    ]
    entrances = [
        item
        for item in scene_data["elements"]
        if item["semantic_role"] in {"main_entrance", "secondary_entrance"}
    ]
    index = start_index
    up = Vector((0, 0, 1))
    for boundary in boundaries:
        bounds = boundary["bounding_box"]
        x0, y0, _ = bounds["minimum"]
        x1, y1, z1 = bounds["maximum"]
        ground_z = max(0.0, z1)
        sides = (
            ("south", "x", y0, x0, x1),
            ("north", "x", y1, x0, x1),
            ("west", "y", x0, y0, y1),
            ("east", "y", x1, y0, y1),
        )
        for side_name, run_axis, fixed, run_start, run_end in sides:
            gaps: list[tuple[float, float]] = []
            for entrance in entrances:
                gate = entrance["bounding_box"]
                gx0, gy0, _ = gate["minimum"]
                gx1, gy1, _ = gate["maximum"]
                touches = (
                    gy0 - 0.75 <= fixed <= gy1 + 0.75
                    if run_axis == "x"
                    else gx0 - 0.75 <= fixed <= gx1 + 0.75
                )
                if touches:
                    interval = (gx0, gx1) if run_axis == "x" else (gy0, gy1)
                    gaps.append((interval[0] - 0.35, interval[1] + 0.35))
            axis = Vector((1, 0, 0)) if run_axis == "x" else Vector((0, 1, 0))
            cross = Vector((0, 1, 0)) if run_axis == "x" else Vector((1, 0, 0))
            for run_number, (left, right) in enumerate(
                _subtract_intervals((run_start, run_end), gaps), start=1
            ):
                length = right - left
                run_center = (left + right) / 2
                center = (
                    Vector((run_center, fixed, ground_z))
                    if run_axis == "x"
                    else Vector((fixed, run_center, ground_z))
                )
                index += 1
                # A low masonry/concrete wall with open steel infill is the normal industrial
                # boundary language here. Keep it transparent enough to present the factory.
                plinth_height = 0.60 if boundary_kit == "mesh_low_plinth" else 0.32
                _oriented_box(
                    f"{boundary['scene_element_id']}:{side_name}-{run_number}:plinth",
                    center + up * (plinth_height / 2),
                    ((axis, length), (cross, 0.22), (up, plinth_height)),
                    material,
                    index,
                    semantic_role="site_boundary",
                )
                for rail_height in (0.72, 2.05):
                    index += 1
                    _oriented_box(
                        f"{boundary['scene_element_id']}:{side_name}-{run_number}:rail-{rail_height}",
                        center + up * rail_height,
                        ((axis, length), (cross, 0.10), (up, 0.10)),
                        material,
                        index,
                        semantic_role="site_boundary",
                    )
                post_count = max(1, int(np.ceil(length / 4.0)))
                for post_number in range(post_count + 1):
                    position = left + length * post_number / post_count
                    post_center = (
                        Vector((position, fixed, ground_z + 1.10))
                        if run_axis == "x"
                        else Vector((fixed, position, ground_z + 1.10))
                    )
                    index += 1
                    _oriented_box(
                        f"{boundary['scene_element_id']}:{side_name}-{run_number}:post-{post_number}",
                        post_center,
                        ((axis, 0.14), (cross, 0.18), (up, 2.20)),
                        material,
                        index,
                        semantic_role="site_boundary",
                    )
                infill_spacing = {
                    "preserve_model": 1.8,
                    "mesh_low_plinth": 0.9,
                    "vertical_bar": 0.42,
                }.get(boundary_kit, 1.8)
                infill_count = min(240, max(1, int(length / infill_spacing)))
                infill_width = 0.035 if boundary_kit == "mesh_low_plinth" else 0.055
                for infill_number in range(1, infill_count):
                    position = left + length * infill_number / infill_count
                    infill_center = (
                        Vector((position, fixed, ground_z + 1.36))
                        if run_axis == "x"
                        else Vector((fixed, position, ground_z + 1.36))
                    )
                    index += 1
                    _oriented_box(
                        f"{boundary['scene_element_id']}:{side_name}-{run_number}:"
                        f"infill-{infill_number}",
                        infill_center,
                        ((axis, infill_width), (cross, 0.055), (up, 1.36)),
                        material,
                        index,
                        semantic_role="site_boundary",
                    )
    return index


def _create_auxiliary_details(
    scene_data: dict,
    materials: dict,
    start_index: int,
) -> int:
    """Give authored support blocks restrained service doors on their road-facing side."""

    roads = [item for item in scene_data["elements"] if item["semantic_role"] == "site_road"]
    if not roads:
        return start_index
    road_centers = [
        Vector(
            (
                (road["bounding_box"]["minimum"][0] + road["bounding_box"]["maximum"][0]) / 2,
                (road["bounding_box"]["minimum"][1] + road["bounding_box"]["maximum"][1]) / 2,
                0,
            )
        )
        for road in roads
    ]
    index = start_index
    up = Vector((0, 0, 1))
    for element in scene_data["elements"]:
        if element["semantic_role"] != "utility_block":
            continue
        bounds = element["bounding_box"]
        x0, y0, z0 = bounds["minimum"]
        x1, y1, z1 = bounds["maximum"]
        height = z1 - z0
        if height < 1.6:
            continue
        candidates = (
            (Vector(((x0 + x1) / 2, y0, 0)), Vector((1, 0, 0)), Vector((0, -1, 0)), x1 - x0),
            (Vector(((x0 + x1) / 2, y1, 0)), Vector((1, 0, 0)), Vector((0, 1, 0)), x1 - x0),
            (Vector((x0, (y0 + y1) / 2, 0)), Vector((0, 1, 0)), Vector((-1, 0, 0)), y1 - y0),
            (Vector((x1, (y0 + y1) / 2, 0)), Vector((0, 1, 0)), Vector((1, 0, 0)), y1 - y0),
        )
        face_center, lateral, normal, face_width = min(
            candidates,
            key=lambda candidate: min(
                (candidate[0] - road_center).length for road_center in road_centers
            ),
        )
        door_height = min(2.4, height * 0.82)
        door_width = min(1.4, max(0.9, face_width * 0.16))
        door_center = face_center - lateral * min(face_width * 0.22, 2.0)
        index += 1
        _oriented_box(
            f"{element['scene_element_id']}:service-door",
            door_center + up * (z0 + door_height / 2) + normal * 0.08,
            ((lateral, door_width), (up, door_height), (normal, 0.12)),
            materials["loading_dock"],
            index,
        )
        louver_width = min(2.4, max(1.0, face_width * 0.22))
        index += 1
        _oriented_box(
            f"{element['scene_element_id']}:service-louver",
            face_center
            + lateral * min(face_width * 0.22, 2.0)
            + up * (z0 + height * 0.58)
            + normal * 0.07,
            ((lateral, louver_width), (up, min(1.0, height * 0.28)), (normal, 0.10)),
            materials["door_shutter"],
            index,
        )
    return index


def create_design_details(
    scene_data: dict,
    design_data: dict,
    start_index: int,
    asset_data: dict | None = None,
) -> int:
    surfaces = {surface["surface_id"]: surface for surface in scene_data["surfaces"]}
    elements = {element["scene_element_id"]: element for element in scene_data["elements"]}
    has_roof_assemblies = bool(design_data.get("roof_assemblies"))
    assembly_by_building = {
        building_id: assembly
        for assembly in design_data.get("roof_assemblies", [])
        for building_id in assembly["building_ids"]
    }
    resolved_materials = build_materials(design_data, asset_data)
    detail_materials = {
        "seam": resolved_materials["panel_seam"],
        "dock": resolved_materials["loading_dock"],
        "glass": resolved_materials["office_glass"],
        "accent": resolved_materials["facade_accent"],
        "secondary": resolved_materials["facade_secondary"],
        "boundary": resolved_materials["site_boundary"],
        "roof": resolved_materials["roof"],
        "shutter": resolved_materials["door_shutter"],
        "biophilic": resolved_materials["tree_foliage"],
    }
    preferences = design_data.get("design_preferences", {})
    boundary_kit = preferences.get("boundary_kit", "preserve_model")
    gate_kit = preferences.get("gate_kit", "preserve_model")
    envelope_kit = preferences.get("envelope_kit", "profiled_metal_vertical")
    facade_rhythm_kit = preferences.get("facade_rhythm_kit", "mixed_restrained")
    detail_index = _create_site_fence(
        scene_data,
        resolved_materials["site_boundary"],
        start_index,
        boundary_kit,
    )
    detail_index = _create_auxiliary_details(scene_data, resolved_materials, detail_index)
    for entrance in (
        element
        for element in scene_data["elements"]
        if element["semantic_role"] in {"main_entrance", "secondary_entrance"}
    ):
        bounds = entrance["bounding_box"]
        x0, y0, _ = bounds["minimum"]
        x1, y1, z1 = bounds["maximum"]
        size_x = x1 - x0
        size_y = y1 - y0
        if min(size_x, size_y) <= 0.3:
            continue
        span_axis = Vector((1, 0, 0)) if size_x >= size_y else Vector((0, 1, 0))
        traffic_axis = Vector((0, 1, 0)) if size_x >= size_y else Vector((1, 0, 0))
        opening_width = max(size_x, size_y)
        center = Vector(((x0 + x1) / 2, (y0 + y1) / 2, z1))
        is_sliding_gate = gate_kit == "industrial_sliding"
        # Preserve the authored traffic width and avoid a tall ceremonial portal.
        post_height = 2.45 if is_sliding_gate else 2.2
        post_size = min(0.42 if is_sliding_gate else 0.28, opening_width * 0.045)
        gate_material = detail_materials["boundary"]
        for side, direction in (("left", -1), ("right", 1)):
            detail_index += 1
            post_center = (
                center
                + span_axis * direction * (opening_width / 2 - post_size / 2)
                + Vector((0, 0, post_height / 2))
            )
            _oriented_box(
                f"{entrance['scene_element_id']}:gate-post-{side}",
                post_center,
                (
                    (span_axis, post_size),
                    (traffic_axis, max(0.55, post_size)),
                    (Vector((0, 0, 1)), post_height),
                ),
                gate_material,
                detail_index,
                semantic_role=entrance["semantic_role"],
            )
        # The semantic rectangle is a traffic opening, not a closed leaf. Park the restrained
        # metal leaf beside that opening so every kit remains visibly truck-capable. Its location,
        # width and connection to the fence remain derived from the authored entrance geometry.
        leaf_center = center + span_axis * opening_width
        for rail_name, rail_height in (("bottom", 0.32), ("middle", 1.08), ("top", 2.02)):
            detail_index += 1
            _oriented_box(
                f"{entrance['scene_element_id']}:gate-rail-{rail_name}",
                leaf_center + Vector((0, 0, rail_height)),
                (
                    (span_axis, opening_width - post_size * 2),
                    (traffic_axis, 0.10),
                    (Vector((0, 0, 1)), 0.10),
                ),
                gate_material,
                detail_index,
                semantic_role=entrance["semantic_role"],
            )
        gate_spacing = 0.55 if gate_kit == "industrial_sliding" else 0.32
        picket_count = max(6, int(opening_width / gate_spacing))
        for picket_number in range(1, picket_count):
            detail_index += 1
            offset = -opening_width / 2 + opening_width * picket_number / picket_count
            _oriented_box(
                f"{entrance['scene_element_id']}:gate-picket-{picket_number:02d}",
                leaf_center + span_axis * offset + Vector((0, 0, 1.17)),
                (
                    (span_axis, 0.055),
                    (traffic_axis, 0.08),
                    (Vector((0, 0, 1)), 1.70),
                ),
                gate_material,
                detail_index,
                semantic_role=entrance["semantic_role"],
            )
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
            if facade_rhythm_kit == "horizontal_restrained":
                horizontal_count = max(2, min(8, int(height / 1.8)))
                for seam_number in range(1, horizontal_count):
                    detail_index += 1
                    _detail_box(
                        f"{facade['surface_id']}:horizontal-joint-{seam_number:02d}",
                        surface,
                        width / 2,
                        height * seam_number / horizontal_count,
                        width * 0.99,
                        0.028,
                        0.045,
                        detail_materials["seam"],
                        detail_index,
                    )
            else:
                seam_step = module * (0.5 if envelope_kit == "profiled_metal_vertical" else 1.0)
                seam_count = int(width // seam_step)
                for seam_number in range(1, seam_count + 1):
                    detail_index += 1
                    _detail_box(
                        f"{facade['surface_id']}:seam-{seam_number:03d}",
                        surface,
                        min(seam_number * seam_step, width - 0.03),
                        height / 2,
                        0.025 if envelope_kit == "sandwich_panel_flat" else 0.035,
                        height * 0.96,
                        0.045 if envelope_kit == "sandwich_panel_flat" else 0.06,
                        detail_materials["seam"],
                        detail_index,
                    )
            # Long eave facades receive a continuous gutter and regularly spaced downpipes.
            # These are dimensioned construction details, not decorative motifs, and materially
            # reduce the featureless-CGI appearance of long LOD100 industrial elevations.
            assembly_bounds = assembly["bounding_box"] if assembly else None
            assembly_long_span = (
                max(
                    assembly_bounds["maximum"][0] - assembly_bounds["minimum"][0],
                    assembly_bounds["maximum"][1] - assembly_bounds["minimum"][1],
                )
                if assembly_bounds
                else width
            )
            if width >= 24.0 and width >= assembly_long_span * 0.70:
                protected_openings = [
                    (
                        dock["u"] * width - dock["width_m"] / 2 - 0.8,
                        dock["u"] * width + dock["width_m"] / 2 + 0.8,
                    )
                    for dock in facade["loading_docks"]
                ]
                facade_entrance = facade.get("office_entrance")
                if facade_entrance:
                    protected_openings.append(
                        (
                            facade_entrance["u"] * width - facade_entrance["width_m"] - 0.8,
                            facade_entrance["u"] * width + facade_entrance["width_m"] + 0.8,
                        )
                    )
                detail_index += 1
                _detail_box(
                    f"{facade['surface_id']}:eave-gutter",
                    surface,
                    width / 2,
                    max(0.35, height - 0.16),
                    width * 0.99,
                    0.22,
                    0.24,
                    detail_materials["secondary"],
                    detail_index,
                    semantic_role="design_detail",
                )
                downpipe_count = max(2, int(np.ceil(width / 24.0)))
                for pipe_number in range(downpipe_count + 1):
                    pipe_u = width * pipe_number / downpipe_count
                    if pipe_u <= 0.25 or pipe_u >= width - 0.25:
                        continue
                    if any(start <= pipe_u <= end for start, end in protected_openings):
                        continue
                    detail_index += 1
                    _detail_box(
                        f"{facade['surface_id']}:downpipe-{pipe_number:02d}",
                        surface,
                        pipe_u,
                        plinth_height + (height - plinth_height) / 2,
                        0.14,
                        max(0.5, height - plinth_height),
                        0.18,
                        detail_materials["secondary"],
                        detail_index,
                        semantic_role="design_detail",
                    )
            clerestory_height = min(
                float(articulation.get("clerestory_band_height_m", 0.0)), height * 0.16
            )
            if width >= 30.0 and height >= 8.0 and clerestory_height >= 0.45:
                clerestory_sill = height * float(articulation.get("clerestory_sill_ratio", 0.62))
                clerestory_center_z = min(
                    height - parapet_height - clerestory_height / 2 - 0.25,
                    clerestory_sill + clerestory_height / 2,
                )
                detail_index += 1
                _detail_box(
                    f"{facade['surface_id']}:clerestory-band",
                    surface,
                    width / 2,
                    clerestory_center_z,
                    width * 0.94,
                    clerestory_height,
                    0.10,
                    detail_materials["glass"],
                    detail_index,
                    semantic_role="glazing",
                )
                mullion_count = max(2, int(width / 7.2))
                for mullion_number in range(1, mullion_count):
                    detail_index += 1
                    _detail_box(
                        f"{facade['surface_id']}:clerestory-mullion-{mullion_number:02d}",
                        surface,
                        width * mullion_number / mullion_count,
                        clerestory_center_z,
                        0.10,
                        clerestory_height,
                        0.14,
                        detail_materials["secondary"],
                        detail_index,
                        semantic_role="glazing",
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
            biophilic_interval = int(articulation.get("biophilic_bay_interval", 0))
            if biophilic_interval and width >= 36.0 and height >= 7.0:
                trellis_width = min(
                    float(articulation.get("biophilic_bay_width_m", 1.4)),
                    module * 2.2,
                )
                trellis_depth = float(articulation.get("biophilic_screen_depth_m", 0.4))
                occupied = [
                    (
                        dock["u"] * width - dock["width_m"] / 2 - 1.8,
                        dock["u"] * width + dock["width_m"] / 2 + 1.8,
                    )
                    for dock in facade["loading_docks"]
                ]
                entrance = facade.get("office_entrance")
                if entrance:
                    occupied.append(
                        (
                            entrance["u"] * width - entrance["width_m"] * 2.0,
                            entrance["u"] * width + entrance["width_m"] * 2.0,
                        )
                    )
                for bay_number in range(biophilic_interval, seam_count, biophilic_interval):
                    u_center = min(bay_number * module, width - trellis_width)
                    if any(start <= u_center <= end for start, end in occupied):
                        continue
                    screen_height = max(3.6, height - plinth_height - parapet_height - 0.8)
                    screen_center_z = plinth_height + screen_height / 2 + 0.2
                    detail_index += 1
                    _detail_box(
                        f"{facade['surface_id']}:biophilic-infill-{bay_number:03d}",
                        surface,
                        u_center,
                        screen_center_z,
                        trellis_width * 0.72,
                        screen_height * 0.92,
                        max(0.12, trellis_depth * 0.55),
                        detail_materials["biophilic"],
                        detail_index,
                        semantic_role="design_detail",
                    )
                    for rail_side in (-1.0, 1.0):
                        detail_index += 1
                        _detail_box(
                            f"{facade['surface_id']}:biophilic-rail-{bay_number:03d}-{rail_side:+g}",
                            surface,
                            u_center + rail_side * trellis_width * 0.43,
                            screen_center_z,
                            0.10,
                            screen_height,
                            trellis_depth,
                            detail_materials["secondary"],
                            detail_index,
                            semantic_role="design_detail",
                        )
                    for cross_number in range(1, 5):
                        detail_index += 1
                        _detail_box(
                            f"{facade['surface_id']}:biophilic-cross-{bay_number:03d}-{cross_number}",
                            surface,
                            u_center,
                            plinth_height + screen_height * cross_number / 5,
                            trellis_width,
                            0.08,
                            trellis_depth,
                            detail_materials["secondary"],
                            detail_index,
                            semantic_role="design_detail",
                        )
            for dock_number, dock in enumerate(facade["loading_docks"], start=1):
                clear_height = float(dock.get("clear_height_m", 4.5))
                door_center_z = clear_height / 2
                detail_index += 1
                _detail_box(
                    dock["dock_id"],
                    surface,
                    dock["u"] * width,
                    door_center_z,
                    dock["width_m"],
                    clear_height,
                    0.16,
                    detail_materials["dock"],
                    detail_index,
                    semantic_role="loading_zone",
                )
                # A recessed dark frame plus a lighter sectional shutter reads as a real
                # industrial door at both aerial and human eye-level views.
                detail_index += 1
                shutter_width = max(0.8, dock["width_m"] - 0.46)
                shutter_height = max(3.0, clear_height - 0.34)
                _detail_box(
                    f"{dock['dock_id']}:shutter",
                    surface,
                    dock["u"] * width,
                    shutter_height / 2 + 0.08,
                    shutter_width,
                    shutter_height,
                    0.20,
                    detail_materials["shutter"],
                    detail_index,
                    semantic_role="loading_zone",
                )
                slat_count = max(7, int(shutter_height / 0.46))
                for slat_number in range(1, slat_count):
                    detail_index += 1
                    _detail_box(
                        f"{dock['dock_id']}:slat-{slat_number:02d}",
                        surface,
                        dock["u"] * width,
                        0.08 + slat_number * shutter_height / slat_count,
                        shutter_width * 0.94,
                        0.035,
                        0.23,
                        detail_materials["seam"],
                        detail_index,
                        semantic_role="loading_zone",
                    )
                frame = surface["frame"]
                origin = Vector(frame["origin"])
                u_axis = Vector(frame["u_axis"])
                v_axis = Vector(frame["v_axis"])
                normal = Vector(frame["normal"])
                dock_u = dock["u"] * width
                frame_width = 0.22
                # Explicit jambs/head stop the opening reading as a generic black rectangle.
                for frame_name, frame_u, frame_z, member_width, member_height in (
                    (
                        "left-jamb",
                        dock_u - dock["width_m"] / 2,
                        door_center_z,
                        frame_width,
                        clear_height,
                    ),
                    (
                        "right-jamb",
                        dock_u + dock["width_m"] / 2,
                        door_center_z,
                        frame_width,
                        clear_height,
                    ),
                    ("head", dock_u, clear_height, dock["width_m"] + frame_width, frame_width),
                ):
                    detail_index += 1
                    _detail_box(
                        f"{dock['dock_id']}:{frame_name}",
                        surface,
                        frame_u,
                        frame_z,
                        member_width,
                        member_height,
                        0.28,
                        detail_materials["secondary"],
                        detail_index,
                        semantic_role="loading_zone",
                    )
                canopy_projection = float(dock.get("canopy_projection_m", 1.2))
                if canopy_projection > 0:
                    detail_index += 1
                    canopy_center = (
                        origin
                        + u_axis * dock_u
                        + v_axis * (clear_height + 0.45)
                        + normal * (canopy_projection / 2 + 0.08)
                    )
                    _oriented_box(
                        f"{dock['dock_id']}:weather-canopy",
                        canopy_center,
                        (
                            (u_axis, dock["width_m"] + 0.8),
                            (normal, canopy_projection),
                            (v_axis, 0.18),
                        ),
                        detail_materials["secondary"],
                        detail_index,
                        semantic_role="loading_zone",
                    )
                if dock.get("include_safety_bollards", True):
                    for side, bollard_u in (
                        ("left", dock_u - dock["width_m"] / 2 - 0.38),
                        ("right", dock_u + dock["width_m"] / 2 + 0.38),
                    ):
                        detail_index += 1
                        _detail_box(
                            f"{dock['dock_id']}:bollard-{side}",
                            surface,
                            bollard_u,
                            0.55,
                            0.18,
                            1.10,
                            0.42,
                            detail_materials["secondary"],
                            detail_index,
                            semantic_role="loading_zone",
                        )
                # One personnel egress door per logistics group supplies a credible hierarchy
                # without repeating domestic-looking doors beside every shutter.
                if dock_number == 1:
                    personnel_u = min(width - 0.7, dock_u + dock["width_m"] / 2 + 1.45)
                    detail_index += 1
                    _detail_box(
                        f"{dock['dock_id']}:personnel-door",
                        surface,
                        personnel_u,
                        1.10,
                        1.05,
                        2.20,
                        0.18,
                        detail_materials["secondary"],
                        detail_index,
                        semantic_role="loading_zone",
                    )
            entrance = facade.get("office_entrance")
            if entrance:
                glazing_ratio = articulation.get("office_glazing_ratio", 0.72)
                element_role = elements[building["building_id"]]["semantic_role"]
                glazing_width = width * glazing_ratio
                if element_role == "main_shed":
                    # An integrated office bay on a shed must not turn most of a 100 m+
                    # industrial facade into curtain wall.
                    glazing_width = min(glazing_width, max(8.0, entrance["width_m"] * 4.0))
                glazing_center_u = entrance["u"] * width
                glazing_center_u = min(
                    width - glazing_width / 2, max(glazing_width / 2, glazing_center_u)
                )
                glazing_height = max(3.2, height * 0.78)
                glazing_center_z = glazing_height / 2
                frame_depth = articulation.get("feature_frame_depth_m", 0.55)
                detail_index += 1
                _detail_box(
                    f"{facade['surface_id']}:glass-band",
                    surface,
                    glazing_center_u,
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
                    ("left", glazing_center_u - glazing_width / 2),
                    ("right", glazing_center_u + glazing_width / 2),
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
                    glazing_center_u,
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
                        glazing_center_u
                        - glazing_width / 2
                        + glazing_width * fin_number / (fin_count + 1),
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
    return detail_index


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


def _configure_engine(profile: str) -> None:
    scene = bpy.context.scene
    if profile == "premium_cycles":
        scene.render.engine = "CYCLES"
        scene.cycles.device = "GPU"
        scene.cycles.use_adaptive_sampling = True
        scene.cycles.adaptive_threshold = 0.02
        scene.cycles.samples = 128
        scene.cycles.use_denoising = True
        preferences = bpy.context.preferences.addons["cycles"].preferences
        preferences.compute_device_type = "OPTIX"
        preferences.get_devices()
        gpu_devices = [device for device in preferences.devices if device.type in {"OPTIX", "CUDA"}]
        if not gpu_devices:
            raise RuntimeError("premium_cycles requires an NVIDIA CUDA/OptiX GPU worker")
        for device in preferences.devices:
            device.use = device in gpu_devices
        return
    try:
        scene.render.engine = "BLENDER_EEVEE_NEXT"
    except TypeError:
        scene.render.engine = "BLENDER_EEVEE"


def configure_world(
    width: int,
    height: int,
    design_data: dict | None = None,
    profile: str = "standard_eevee",
    asset_data: dict | None = None,
) -> None:
    scene = bpy.context.scene
    _configure_engine(profile)
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
    sky.name = "V365 Physical Sky"
    sky.sky_type = "NISHITA"
    sky.sun_rotation = sun_azimuth
    sky.sun_elevation = sun_elevation
    sky.air_density = 1.1
    sky.dust_density = 1.4
    sky.ozone_density = 1.0
    sky_background = world_tree.nodes.new("ShaderNodeBackground")
    sky_background.name = "V365 Sky Background"
    # Keep skylight as fill rather than flattening all facade/ground values. Direct sun then
    # creates readable contact shadows while AgX protects the light metal roof highlights.
    sky_background.inputs["Strength"].default_value = 0.45
    camera_background = world_tree.nodes.new("ShaderNodeBackground")
    camera_background.name = "V365 Camera Background"
    # Headless EGL can return a black camera background for Nishita even while its lighting is
    # valid.  A neutral daylight plate keeps Base RGB useful as image-generation authority.
    camera_background.inputs["Color"].default_value = (0.32, 0.52, 0.78, 1.0)
    camera_background.inputs["Strength"].default_value = 0.55
    output = world_tree.nodes.new("ShaderNodeOutputWorld")
    world_tree.links.new(sky.outputs["Color"], sky_background.inputs["Color"])
    camera_mix = None
    if profile == "premium_cycles":
        light_path = world_tree.nodes.new("ShaderNodeLightPath")
        camera_mix = world_tree.nodes.new("ShaderNodeMixShader")
        camera_mix.name = "V365 Camera Mix"
        world_tree.links.new(light_path.outputs["Is Camera Ray"], camera_mix.inputs[0])
        world_tree.links.new(camera_background.outputs["Background"], camera_mix.inputs[2])

    environment_file = None
    asset_root = (
        Path(asset_data["_asset_root"]) if asset_data and asset_data.get("_asset_root") else None
    )
    for asset in (asset_data or {}).get("assets", []):
        if asset.get("kind") != "environment" or "environment_daylight" not in asset.get(
            "semantic_roles", []
        ):
            continue
        candidate = next(
            (item for item in asset.get("files", []) if item.get("role") == "environment"),
            None,
        )
        if candidate and asset_root:
            environment_file = (asset_root / candidate["path"]).resolve()
        break
    if environment_file and environment_file.is_file():
        environment = world_tree.nodes.new("ShaderNodeTexEnvironment")
        environment.image = bpy.data.images.load(str(environment_file), check_existing=True)
        environment_background = world_tree.nodes.new("ShaderNodeBackground")
        environment_background.name = "V365 Environment Background"
        environment_background.inputs["Strength"].default_value = 0.7
        world_tree.links.new(environment.outputs["Color"], environment_background.inputs["Color"])
        if camera_mix:
            world_tree.links.new(environment_background.outputs["Background"], camera_mix.inputs[1])
            world_tree.links.new(camera_mix.outputs["Shader"], output.inputs["Surface"])
        else:
            # Eevee does not provide reliable Light Path values. Use the HDRI directly when one
            # is available rather than letting a Mix Shader resolve to an undefined branch.
            world_tree.links.new(
                environment_background.outputs["Background"], output.inputs["Surface"]
            )
    else:
        if camera_mix:
            world_tree.links.new(sky_background.outputs["Background"], camera_mix.inputs[1])
            world_tree.links.new(camera_mix.outputs["Shader"], output.inputs["Surface"])
        else:
            # Nishita is black in some headless EGL/Eevee workers. The fixed daylight world is
            # intentionally deterministic; the separate Sun still supplies form and shadows.
            world_tree.links.new(camera_background.outputs["Background"], output.inputs["Surface"])
    try:
        scene.view_settings.view_transform = "AgX"
    except TypeError:
        scene.view_settings.view_transform = "Filmic"
    try:
        scene.view_settings.look = "AgX - Medium High Contrast"
    except TypeError:
        scene.view_settings.look = "Medium High Contrast"

    sun_data = bpy.data.lights.new("Sun", type="SUN")
    sun_data.energy = 2.8
    sun_data.angle = math.radians(0.8)
    sun = bpy.data.objects.new("Sun", sun_data)
    sun.rotation_euler = (math.pi / 2 - sun_elevation, 0.0, sun_azimuth)
    bpy.context.collection.objects.link(sun)


def configure_view_lighting(spec: dict, design_data: dict | None = None) -> None:
    """Give photography-specific cameras matching pixel evidence without changing geometry."""

    scene = bpy.context.scene
    environment = design_data.get("environment", {}) if design_data else {}
    base_azimuth = math.radians(float(environment.get("sun_azimuth_deg", 135.0)))
    base_elevation = math.radians(float(environment.get("sun_elevation_deg", 42.0)))
    golden_hour = spec.get("role") == "loading_detail"
    sun_azimuth = base_azimuth + (math.radians(18.0) if golden_hour else 0.0)
    sun_elevation = math.radians(17.0) if golden_hour else base_elevation

    sun = bpy.data.objects.get("Sun")
    if sun is not None and sun.type == "LIGHT":
        sun.rotation_euler = (math.pi / 2 - sun_elevation, 0.0, sun_azimuth)
        sun.data.energy = 2.35 if golden_hour else 2.8
        sun.data.color = (1.0, 0.68, 0.42) if golden_hour else (1.0, 1.0, 1.0)

    if scene.world and scene.world.use_nodes and scene.world.node_tree:
        world_tree = scene.world.node_tree
        sky = world_tree.nodes.get("V365 Physical Sky")
        if sky is not None:
            sky.sun_rotation = sun_azimuth
            sky.sun_elevation = sun_elevation
            sky.dust_density = 2.2 if golden_hour else 1.4
        camera_background = world_tree.nodes.get("V365 Camera Background")
        if camera_background is not None:
            camera_background.inputs["Color"].default_value = (
                (0.48, 0.55, 0.72, 1.0) if golden_hour else (0.32, 0.52, 0.78, 1.0)
            )
            camera_background.inputs["Strength"].default_value = 0.65 if golden_hour else 0.55
        scene.view_settings.exposure = 0.7 if golden_hour else 0.0
        # The Eevee daylight HDRI otherwise remains a strong morning pixel cue and routinely
        # overrides a text-only golden-hour instruction. For this one photography role, use the
        # deterministic sky plate plus warm low sun as conditioning evidence. Restore the normal
        # world source for every other role so rendering a selected subset remains deterministic.
        output = next(
            (node for node in world_tree.nodes if node.bl_idname == "ShaderNodeOutputWorld"),
            None,
        )
        if output is not None:
            camera_mix = world_tree.nodes.get("V365 Camera Mix")
            environment_background = world_tree.nodes.get("V365 Environment Background")
            sky_background = world_tree.nodes.get("V365 Sky Background")
            normal_source = (
                camera_mix or environment_background or sky_background or camera_background
            )
            source = camera_background if golden_hour else normal_source
            if source is not None:
                for link in tuple(output.inputs["Surface"].links):
                    world_tree.links.remove(link)
                output_socket = (
                    source.outputs["Shader"]
                    if source.bl_idname == "ShaderNodeMixShader"
                    else source.outputs["Background"]
                )
                world_tree.links.new(output_socket, output.inputs["Surface"])


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
    context_objects = [
        obj
        for obj in scene.objects
        if obj.type == "MESH" and obj.get("semantic_role") == "context_building"
    ]
    original_visibility = {obj: obj.hide_render for obj in context_objects}
    for obj in context_objects:
        obj.hide_render = True
    layer = scene.view_layers[0]
    layer.use_pass_z = True
    layer.use_pass_normal = True
    scene.use_nodes = True
    tree = scene.node_tree
    tree.nodes.clear()
    render_layers = tree.nodes.new("CompositorNodeRLayers")
    composite = tree.nodes.new("CompositorNodeComposite")
    tree.links.new(render_layers.outputs["Image"], composite.inputs["Image"])
    file_output(tree, render_layers, "Depth", view_dir, "depth_", "OPEN_EXR")
    file_output(tree, render_layers, "Normal", view_dir, "normal_", "OPEN_EXR")
    normalized_depth = tree.nodes.new("CompositorNodeNormalize")
    tree.links.new(render_layers.outputs["Depth"], normalized_depth.inputs["Value"])
    file_output(tree, normalized_depth, "Value", view_dir, "depth_preview_", "PNG")
    scene.render.filepath = str(view_dir / "base_rgb.png")
    try:
        # Keep geometry authority photoreal-friendly. Proxy massing is supplied separately as a
        # camera-registered composition guide and is never overlaid after generative reframing.
        bpy.ops.render.render(write_still=True)
    finally:
        for obj, hidden in original_visibility.items():
            obj.hide_render = hidden
    for prefix, extension in (
        ("depth_", "exr"),
        ("normal_", "exr"),
        ("depth_preview_", "png"),
    ):
        matches = sorted(view_dir.glob(f"{prefix}*.{extension}"))
        if matches:
            name = "depth.png" if prefix == "depth_preview_" else f"{prefix.rstrip('_')}.exr"
            os.replace(matches[-1], view_dir / name)


def render_context_proxy_overlay(view_dir: Path) -> None:
    """Render context sheds as camera-aligned RGBA with project geometry as holdouts."""

    scene = bpy.context.scene
    mesh_objects = [obj for obj in scene.objects if obj.type == "MESH"]
    context_objects = [
        obj for obj in mesh_objects if obj.get("semantic_role") == "context_building"
    ]
    if not context_objects:
        return

    original_materials = {obj: obj.data.materials[0] for obj in mesh_objects}
    original_visibility = {obj: obj.hide_render for obj in mesh_objects}
    original_film_transparent = scene.render.film_transparent
    original_color_mode = scene.render.image_settings.color_mode
    original_format = scene.render.image_settings.file_format
    original_scene_nodes = scene.use_nodes
    original_filepath = scene.render.filepath

    holdout = bpy.data.materials.new("context-proxy-holdout")
    holdout.use_nodes = True
    holdout.node_tree.nodes.clear()
    output = holdout.node_tree.nodes.new("ShaderNodeOutputMaterial")
    holdout_node = holdout.node_tree.nodes.new("ShaderNodeHoldout")
    holdout.node_tree.links.new(holdout_node.outputs["Holdout"], output.inputs["Surface"])

    try:
        for obj in mesh_objects:
            obj.hide_render = False
            if obj not in context_objects:
                obj.data.materials.clear()
                obj.data.materials.append(holdout)
        scene.use_nodes = False
        scene.render.film_transparent = True
        scene.render.image_settings.file_format = "PNG"
        scene.render.image_settings.color_mode = "RGBA"
        scene.render.filepath = str(view_dir / "context_proxy_rgba.png")
        bpy.ops.render.render(write_still=True)
    finally:
        _replace_materials(original_materials)
        for obj, hidden in original_visibility.items():
            obj.hide_render = hidden
        scene.render.film_transparent = original_film_transparent
        scene.render.image_settings.color_mode = original_color_mode
        scene.render.image_settings.file_format = original_format
        scene.use_nodes = original_scene_nodes
        scene.render.filepath = original_filepath


def _replace_materials(materials_by_object: dict) -> None:
    for obj, replacement in materials_by_object.items():
        obj.data.materials.clear()
        obj.data.materials.append(replacement)


def render_masks(view_dir: Path) -> None:
    scene = bpy.context.scene
    previous_engine = scene.render.engine
    _configure_engine("preview_fast")
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
        "site_ground": (0.42, 0.30, 0.16, 1.0),
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
        "facade_secondary": (0.58, 0.16, 0.72, 1.0),
        "glazing": (0.10, 0.52, 0.78, 1.0),
        "brand_accent": (0.86, 0.18, 0.38, 1.0),
        "context_building": (0.42, 0.46, 0.50, 1.0),
        "context_landscape": (0.08, 0.32, 0.10, 1.0),
        "utility_block": (0.95, 0.65, 0.10, 1.0),
        "unknown": (0.55, 0.55, 0.55, 1.0),
        "design_detail": (0.75, 0.20, 0.85, 1.0),
        "tree": (0.04, 0.62, 0.08, 1.0),
        "vehicle": (0.92, 0.82, 0.08, 1.0),
        "person": (0.96, 0.38, 0.08, 1.0),
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
    # ID passes are data, not presentation imagery.  Applying a contrast look mutates the
    # encoded bytes and makes object/semantic IDs impossible to decode deterministically.
    scene.view_settings.look = "None"
    _replace_materials(instance_materials)
    scene.render.filepath = str(view_dir / "instance_id.png")
    bpy.ops.render.render(write_still=True)
    _replace_materials({obj: semantic_materials[obj["semantic_role"]] for obj in mesh_objects})
    scene.render.filepath = str(view_dir / "semantic.png")
    bpy.ops.render.render(write_still=True)
    (view_dir / "semantic_id_manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "color_transform": "Standard/None",
                "roles": [
                    {
                        "semantic_role": role,
                        "linear_rgb": color[:3],
                        "srgb8": [_linear_channel_to_srgb8(channel) for channel in color[:3]],
                    }
                    for role, color in sorted(role_colors.items())
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    _replace_materials(original)
    scene.world.color = previous_world
    scene.view_settings.view_transform = previous_transform
    scene.view_settings.look = previous_look
    scene.render.engine = previous_engine


def render_material_ids(view_dir: Path) -> None:
    """Render stable material regions and persist their versioned asset IDs."""

    scene = bpy.context.scene
    previous_engine = scene.render.engine
    _configure_engine("preview_fast")
    mesh_objects = [obj for obj in scene.objects if obj.type == "MESH"]
    original = {obj: obj.data.materials[0] for obj in mesh_objects}
    material_keys = {
        material: str(material.get("asset_id", f"procedural.{material.name}"))
        for material in set(original.values())
    }
    ordered = sorted(set(material_keys.values()))
    colors = {
        asset_id: (*colorsys.hsv_to_rgb(index / max(1, len(ordered)), 0.82, 1.0), 1.0)
        for index, asset_id in enumerate(ordered)
    }
    replacements = {
        obj: emission_material(f"material_id_{index:03d}", colors[material_keys[material]])
        for index, (obj, material) in enumerate(original.items(), start=1)
    }
    previous_world_nodes = scene.world.use_nodes
    previous_world_color = scene.world.color[:]
    previous_scene_nodes = scene.use_nodes
    previous_transform = scene.view_settings.view_transform
    previous_look = scene.view_settings.look
    scene.use_nodes = False
    scene.world.use_nodes = False
    scene.world.color = (0.0, 0.0, 0.0)
    scene.view_settings.view_transform = "Standard"
    scene.view_settings.look = "None"
    _replace_materials(replacements)
    scene.render.filepath = str(view_dir / "material_id.png")
    bpy.ops.render.render(write_still=True)
    (view_dir / "material_id_manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "materials": [
                    {"asset_id": asset_id, "linear_rgb": colors[asset_id][:3]}
                    for asset_id in ordered
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    _replace_materials(original)
    scene.world.use_nodes = previous_world_nodes
    scene.world.color = previous_world_color
    scene.use_nodes = previous_scene_nodes
    scene.view_settings.view_transform = previous_transform
    scene.view_settings.look = previous_look
    scene.render.engine = previous_engine


def render_control_policy(view_dir: Path) -> None:
    """Render a provider-neutral LOCKED/BOUNDED/FREE policy as RGB channels.

    Red objects are locked in full (authored entrances and site boundaries), green objects may
    receive bounded appearance refinement, and blue objects/background are non-authoritative
    context. Structural and silhouette edge bands are promoted to LOCKED later by the control-pack
    builder, so roof/facade/road interiors can still receive realistic material treatment.
    """

    scene = bpy.context.scene
    previous_engine = scene.render.engine
    _configure_engine("preview_fast")
    mesh_objects = [obj for obj in scene.objects if obj.type == "MESH"]
    original = {obj: obj.data.materials[0] for obj in mesh_objects}
    policy_materials = {
        "locked": emission_material("policy_locked", (1.0, 0.0, 0.0, 1.0)),
        "bounded": emission_material("policy_bounded", (0.0, 1.0, 0.0, 1.0)),
        "free": emission_material("policy_free", (0.0, 0.0, 1.0, 1.0)),
    }
    locked_roles = {"main_entrance", "secondary_entrance", "site_boundary"}
    # Adjoining-building footprints and silhouettes remain spatial evidence. Their appearance
    # is subdued, but a generative pass must not freely relocate or replace them.
    free_roles = {"context_landscape"}
    replacements = {}
    for obj in mesh_objects:
        role = obj.get("semantic_role", "unknown")
        policy = "locked" if role in locked_roles else "free" if role in free_roles else "bounded"
        replacements[obj] = policy_materials[policy]

    previous_world_nodes = scene.world.use_nodes
    previous_world_color = scene.world.color[:]
    previous_scene_nodes = scene.use_nodes
    previous_transform = scene.view_settings.view_transform
    previous_look = scene.view_settings.look
    scene.use_nodes = False
    scene.world.use_nodes = False
    scene.world.color = (0.0, 0.0, 1.0)
    scene.view_settings.view_transform = "Standard"
    scene.view_settings.look = "None"
    _replace_materials(replacements)
    scene.render.filepath = str(view_dir / "control_policy.png")
    bpy.ops.render.render(write_still=True)
    _replace_materials(original)
    scene.world.use_nodes = previous_world_nodes
    scene.world.color = previous_world_color
    scene.use_nodes = previous_scene_nodes
    scene.view_settings.view_transform = previous_transform
    scene.view_settings.look = previous_look
    scene.render.engine = previous_engine


def render_clay_and_edges(view_dir: Path) -> None:
    scene = bpy.context.scene
    previous_engine = scene.render.engine
    _configure_engine("preview_fast")
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
    scene.render.engine = previous_engine


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
    asset_data = None
    if args.asset_library:
        asset_library_path = args.asset_library.resolve()
        asset_data = json.loads(asset_library_path.read_text(encoding="utf-8"))
        asset_data["_asset_root"] = str(asset_library_path.parent)
        if design_data and asset_data.get("library_version") != design_data.get(
            "asset_library_version"
        ):
            raise ValueError("asset library version does not match Design DNA")
    base_object_count = create_objects(scene_data, scene_path.parent, design_data, asset_data)
    if design_data:
        detail_start = create_context_environment(
            scene_data, design_data, base_object_count, asset_data
        )
        detail_end = create_design_details(scene_data, design_data, detail_start, asset_data)
        _, entourage = create_deterministic_entourage(
            scene_data,
            scene_path.parent,
            design_data,
            detail_end,
            asset_data,
        )
        (output / "entourage_manifest.json").write_text(
            json.dumps(
                {
                    "schema_version": "1.0.0",
                    "design_revision": design_data.get("design_revision"),
                    "density": design_data.get("presentation", {}).get("entourage_density", "low"),
                    "instances": entourage,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        batch_noncanonical_details(base_object_count)
    default_size = {
        "preview_fast": (768, 432),
        "standard_eevee": (1024, 576),
        "premium_cycles": (2048, 1152),
    }[args.profile]
    configure_world(
        args.width or default_size[0],
        args.height or default_size[1],
        design_data,
        args.profile,
        asset_data,
    )
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
        configure_view_lighting(camera_spec, design_data)
        camera = configure_camera(camera_spec)
        render_pbr(view_dir)
        # Photographic exposure belongs only to Base RGB. Semantic/material/control passes rely
        # on exact encoded colours and must never inherit the golden-hour exposure transform.
        bpy.context.scene.view_settings.exposure = 0.0
        render_context_proxy_overlay(view_dir)
        if not args.pbr_only:
            render_masks(view_dir)
            render_material_ids(view_dir)
            render_clay_and_edges(view_dir)
            render_control_policy(view_dir)
        bpy.data.objects.remove(camera, do_unlink=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(output / "designed_scene.blend"))


main()
