"""Build one shared Blender scene and render all persisted cameras.

Executed by Blender, not the control-plane Python environment.
"""

from __future__ import annotations

import argparse
import json
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
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--width", type=int, default=768)
    parser.add_argument("--height", type=int, default=432)
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
    return value


def build_materials():
    return {
        "main_shed": material("main_shed", (0.58, 0.62, 0.65, 1), 0.45, 0.34),
        "office_block": material("office_block", (0.12, 0.28, 0.38, 1), 0.18, 0.22),
        "service_yard": material("service_yard", (0.25, 0.27, 0.28, 1), 0.0, 0.78),
        "utility_block": material("utility_block", (0.38, 0.42, 0.44, 1), 0.2, 0.5),
        "unknown": material("unknown", (0.45, 0.47, 0.48, 1), 0.0, 0.55),
    }


def create_objects(scene_data: dict, scene_root: Path) -> None:
    materials = build_materials()
    for index, element in enumerate(scene_data["elements"], start=1):
        arrays = np.load(scene_root / element["mesh_ref"])
        vertices = arrays["vertices"].tolist()
        faces = arrays["faces"].tolist()
        mesh = bpy.data.meshes.new(element["scene_element_id"])
        mesh.from_pydata(vertices, [], faces)
        mesh.update()
        obj = bpy.data.objects.new(element["scene_element_id"], mesh)
        obj.pass_index = index
        obj["source_external_id"] = element["source"]["external_id"]
        obj["semantic_role"] = element["semantic_role"]
        obj.data.materials.append(materials[element["semantic_role"]])
        bpy.context.collection.objects.link(obj)


def configure_world(width: int, height: int) -> None:
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE_NEXT"
    scene.render.resolution_x = width
    scene.render.resolution_y = height
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"
    scene.render.film_transparent = False
    scene.world.color = (0.04, 0.06, 0.09)

    sun_data = bpy.data.lights.new("Sun", type="SUN")
    sun_data.energy = 3.0
    sun_data.angle = 0.08
    sun = bpy.data.objects.new("Sun", sun_data)
    sun.rotation_euler = (0.75, -0.35, -0.8)
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
    node.format.color_mode = "RGB" if socket_name == "Normal" else "BW"
    tree.links.new(source.outputs[socket_name], node.inputs[0])


def render_pbr(view_dir: Path) -> None:
    scene = bpy.context.scene
    layer = scene.view_layers[0]
    layer.use_pass_z = True
    layer.use_pass_normal = True
    layer.use_pass_object_index = True
    scene.use_nodes = True
    tree = scene.node_tree
    tree.nodes.clear()
    render_layers = tree.nodes.new("CompositorNodeRLayers")
    file_output(tree, render_layers, "Depth", view_dir, "depth_", "OPEN_EXR")
    file_output(tree, render_layers, "Normal", view_dir, "normal_", "OPEN_EXR")
    file_output(tree, render_layers, "IndexOB", view_dir, "instance_id_", "OPEN_EXR")
    scene.render.filepath = str(view_dir / "base_rgb.png")
    bpy.ops.render.render(write_still=True)
    for prefix in ("depth_", "normal_", "instance_id_"):
        matches = sorted(view_dir.glob(f"{prefix}*.exr"))
        if matches:
            os.replace(matches[-1], view_dir / f"{prefix.rstrip('_')}.exr")


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
    create_objects(scene_data, scene_path.parent)
    configure_world(args.width, args.height)
    for camera_spec in view_set["cameras"]:
        view_dir = output / camera_spec["view_id"]
        view_dir.mkdir(parents=True, exist_ok=True)
        camera = configure_camera(camera_spec)
        render_pbr(view_dir)
        render_clay_and_edges(view_dir)
        bpy.data.objects.remove(camera, do_unlink=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(output / "designed_scene.blend"))


main()
