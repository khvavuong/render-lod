"""The conditioning renders may only be reused while their inputs still hold.

The check already re-reads each rendered `camera.json` and refuses the cache
when a camera moved, so a re-planned view set is never judged through the old
angles. What it did not notice is the other half: the same camera pointed at a
different scene. Re-importing a model rewrites the semantic pass the gate
measures — new roles, new surfaces, the same cameras — and those renders were
reused unchanged.

The renderer already writes the digest of every file it read. Those are the
cache key.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from v365_archviz.application.run_generation_job import RunGenerationJob, _JobPaths
from v365_archviz.domain.workflow import Camera, ViewRole, ViewSet

#: Every file the renderer writes per view, as `_conditioning_complete` checks.
PACK_FILES = (
    "base_rgb.png",
    "depth.png",
    "instance_id.png",
    "semantic.png",
    "semantic_id_manifest.json",
    "material_id.png",
    "material_id_manifest.json",
    "edges.png",
    "control_policy.png",
    "structure_guide.png",
    "locked_mask.png",
    "bounded_mask.png",
    "free_mask.png",
    "control_pack_manifest.json",
    "project_locked_mask.png",
    "project_designable_mask.png",
    "context_ground_mask.png",
    "context_proxy_mask.png",
    "layer_authority_manifest.json",
)


def view_set_of(x: float) -> ViewSet:
    return ViewSet(
        view_set_id="model-design-standard-v40",
        design_revision="design",
        cameras=(
            Camera(
                view_id="view-01",
                role=ViewRole.OVERALL,
                position=(x, 0.0, 10.0),
                target=(0.0, 0.0, 0.0),
                focal_length_mm=35,
                sensor_width_mm=36,
                aspect_ratio="16:9",
            ),
        ),
    )


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rendered(root: Path, view_set: ViewSet) -> _JobPaths:
    """A render root as the renderer leaves it, with the inputs it read."""

    root.mkdir(parents=True, exist_ok=True)
    scene = root / "canonical_scene.json"
    design_dna = root / "design_dna.json"
    view_set_path = root / "view_set.json"
    scene.write_text("{}", encoding="utf-8")
    design_dna.write_text("{}", encoding="utf-8")
    view_set_path.write_text(view_set.model_dump_json(indent=2) + "\n", encoding="utf-8")
    render_root = root / "renders"
    for camera in view_set.cameras:
        view_root = render_root / camera.view_id
        view_root.mkdir(parents=True, exist_ok=True)
        for name in PACK_FILES:
            (view_root / name).write_bytes(b"x")
        # Re-read and compared against the plan, so it has to be the real camera.
        (view_root / "camera.json").write_text(
            camera.model_dump_json(indent=2), encoding="utf-8"
        )
    (render_root / "render_manifest.json").write_text(
        json.dumps(
            {
                "view_set_id": view_set.view_set_id,
                "view_set_sha256": digest(view_set_path),
                "scene_sha256": digest(scene),
                "design_dna_sha256": digest(design_dna),
            }
        ),
        encoding="utf-8",
    )
    return _JobPaths(
        scene=scene,
        design_dna=design_dna,
        view_set=view_set_path,
        render_root=render_root,
        generated_root=root / "generated",
    )


class TestReuse:
    def test_untouched_renders_are_reused(self, tmp_path: Path) -> None:
        view_set = view_set_of(100.0)
        paths = rendered(tmp_path, view_set)
        assert RunGenerationJob._conditioning_complete(paths, view_set) is True

    def test_a_moved_camera_is_not_the_same_render(self, tmp_path: Path) -> None:
        # The identity is unchanged — only the position moved, which is exactly
        # what a planner fix does.
        paths = rendered(tmp_path, view_set_of(100.0))
        moved = view_set_of(250.0)
        paths.view_set.write_text(moved.model_dump_json(indent=2) + "\n", encoding="utf-8")
        assert moved.view_set_id == "model-design-standard-v40"
        assert RunGenerationJob._conditioning_complete(paths, moved) is False

    def test_a_regenerated_scene_is_not_the_same_render(self, tmp_path: Path) -> None:
        # Re-importing the model changes what the semantic pass paints without
        # moving a single camera, and that pass is what the gate measures.
        view_set = view_set_of(100.0)
        paths = rendered(tmp_path, view_set)
        paths.scene.write_text('{"elements": []}', encoding="utf-8")
        assert RunGenerationJob._conditioning_complete(paths, view_set) is False

    def test_a_redesigned_model_is_not_the_same_render(self, tmp_path: Path) -> None:
        view_set = view_set_of(100.0)
        paths = rendered(tmp_path, view_set)
        paths.design_dna.write_text('{"buildings": []}', encoding="utf-8")
        assert RunGenerationJob._conditioning_complete(paths, view_set) is False

    def test_a_manifest_without_digests_is_not_trusted(self, tmp_path: Path) -> None:
        # Written by an older renderer, so nothing says what it rendered.
        view_set = view_set_of(100.0)
        paths = rendered(tmp_path, view_set)
        (paths.render_root / "render_manifest.json").write_text(
            json.dumps({"view_set_id": view_set.view_set_id}), encoding="utf-8"
        )
        assert RunGenerationJob._conditioning_complete(paths, view_set) is False
