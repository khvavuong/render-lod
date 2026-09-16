"""Build deterministic LOCKED/BOUNDED/FREE masks from renderer policy output."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
from numpy.typing import NDArray
from PIL import Image, ImageFilter, ImageOps

from v365_archviz.artifacts import atomic_write
from v365_archviz.domain.controlled_realism import (
    ControlClass,
    ControlMaskArtifact,
    ControlPackManifest,
)
from v365_archviz.errors import InvalidModelError


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _png(mask: NDArray[np.bool_]) -> bytes:
    from io import BytesIO

    buffer = BytesIO()
    Image.fromarray(mask.astype(np.uint8) * 255, mode="L").save(buffer, format="PNG")
    return buffer.getvalue()


def _neutral_structure_guide(base: Image.Image, edges: Image.Image) -> bytes:
    """Remove synthetic material colours while retaining camera-space structure."""
    from io import BytesIO

    luminance = ImageOps.autocontrast(base.convert("L"), cutoff=1)
    neutral = ImageOps.colorize(luminance, black="#20272d", white="#e3e6e5")
    edge_mask = edges.point(lambda value: min(255, value * 2))
    dark_edges = Image.new("RGB", neutral.size, "#151b20")
    guide = Image.composite(dark_edges, neutral, edge_mask)
    buffer = BytesIO()
    guide.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def _semantic_role_masks(
    view_directory: Path, size: tuple[int, int]
) -> dict[str, NDArray[np.bool_]]:
    semantic_path = view_directory / "semantic.png"
    manifest_path = view_directory / "semantic_id_manifest.json"
    if not semantic_path.is_file() or not manifest_path.is_file():
        return {}
    with Image.open(semantic_path) as source:
        semantic = np.asarray(
            source.convert("RGB").resize(size, Image.Resampling.NEAREST), dtype=np.int16
        )
    document = json.loads(manifest_path.read_text(encoding="utf-8"))
    masks: dict[str, NDArray[np.bool_]] = {}
    for item in document.get("roles", []):
        role = str(item["semantic_role"])
        color = np.asarray(item["srgb8"], dtype=np.int16)
        masks[role] = np.max(np.abs(semantic - color), axis=2) <= 4
    return masks


def _write_layer_authority_artifacts(
    view_directory: Path,
    *,
    size: tuple[int, int],
    edge_band: NDArray[np.bool_],
) -> None:
    roles = _semantic_role_masks(view_directory, size)
    shape = (size[1], size[0])

    def combined(names: set[str]) -> NDArray[np.bool_]:
        selected = [mask for role, mask in roles.items() if role in names]
        return np.logical_or.reduce(selected) if selected else np.zeros(shape, dtype=bool)

    context_ground = combined({"context_landscape"})
    context_proxy_path = view_directory / "context_proxy_rgba.png"
    if context_proxy_path.is_file():
        with Image.open(context_proxy_path) as source:
            alpha = np.asarray(
                source.convert("RGBA").resize(size, Image.Resampling.LANCZOS).getchannel("A")
            )
        context_proxy = alpha >= 4
    else:
        context_proxy = combined({"context_building"})
    project_designable = combined(
        {
            "main_shed",
            "office_block",
            "roof",
            "primary_facade",
            "facade_secondary",
            "glazing",
            "brand_accent",
            "design_detail",
        }
    )
    project_locked = (
        combined(
            {
                "service_yard",
                "site_ground",
                "site_road",
                "sidewalk",
                "parking",
                "landscape_zone",
                "main_entrance",
                "secondary_entrance",
                "site_boundary",
                "loading_zone",
                "utility_block",
            }
        )
        | edge_band
    )
    masks = {
        "project_locked": project_locked,
        "project_designable": project_designable & ~project_locked,
        "context_ground": context_ground & ~project_locked,
        "context_proxy": context_proxy & ~project_locked,
    }
    artifacts = {}
    total = shape[0] * shape[1]
    for name, mask in masks.items():
        content = _png(mask)
        target = view_directory / f"{name}_mask.png"
        atomic_write(target, content)
        artifacts[name] = {
            "path": str(target),
            "sha256": _sha256(content),
            "coverage": float(mask.sum()) / total,
        }
    authority = {
        "schema_version": "1.0.0",
        "view_id": view_directory.name,
        "layers": artifacts,
        "authority_order": [
            "project_locked",
            "project_designable",
            "context_ground",
            "context_proxy",
        ],
        "ai_editable_layers": ["project_designable", "context_ground"],
        "composite_order": ["gemini_photoreal", "context_proxy", "brand_watermark"],
    }
    atomic_write(
        view_directory / "layer_authority_manifest.json",
        json.dumps(authority, ensure_ascii=False, indent=2).encode("utf-8") + b"\n",
    )


class BuildControlPack:
    """Convert one RGB policy pass plus protected edges into a validated partition."""

    def execute(
        self,
        view_directory: Path,
        *,
        edge_band_px: int = 1,
        edge_threshold: int = 240,
    ) -> ControlPackManifest:
        policy_path = view_directory / "control_policy.png"
        edge_path = view_directory / "edges.png"
        base_path = view_directory / "base_rgb.png"
        if not policy_path.is_file() or not edge_path.is_file() or not base_path.is_file():
            raise InvalidModelError(f"control inputs are missing for {view_directory.name}")
        try:
            with Image.open(policy_path) as source:
                policy = np.asarray(source.convert("RGB"), dtype=np.uint8)
            with Image.open(edge_path) as source:
                edges = source.convert("L").resize(
                    (policy.shape[1], policy.shape[0]), Image.Resampling.NEAREST
                )
            with Image.open(base_path) as source:
                base = source.convert("RGB").resize(
                    (policy.shape[1], policy.shape[0]), Image.Resampling.LANCZOS
                )
        except OSError as exc:
            raise InvalidModelError(f"cannot read control inputs: {exc}") from exc

        if edge_band_px < 1 or edge_band_px % 2 == 0:
            raise ValueError("edge_band_px must be a positive odd number")
        if not 1 <= edge_threshold <= 255:
            raise ValueError("edge_threshold must be between 1 and 255")
        filtered_edges = (
            edges if edge_band_px == 1 else edges.filter(ImageFilter.MaxFilter(edge_band_px))
        )
        edge_band = np.asarray(filtered_edges) >= edge_threshold
        dominant = np.argmax(policy, axis=2)
        visible = np.max(policy, axis=2) >= 16
        free_source = (dominant == 2) & visible
        locked = ((dominant == 0) & visible) | (edge_band & ~free_source)
        bounded = (dominant == 1) & visible & ~locked
        free = ~(locked | bounded)
        masks = {
            ControlClass.LOCKED: locked,
            ControlClass.BOUNDED: bounded,
            ControlClass.FREE: free,
        }
        stack = np.stack(tuple(masks.values()), axis=0)
        overlap = int(np.count_nonzero(stack.sum(axis=0) > 1))
        uncovered = int(np.count_nonzero(stack.sum(axis=0) == 0))
        total = policy.shape[0] * policy.shape[1]
        artifacts: list[ControlMaskArtifact] = []
        for control_class, mask in masks.items():
            content = _png(mask)
            path = view_directory / f"{control_class.value}_mask.png"
            atomic_write(path, content)
            artifacts.append(
                ControlMaskArtifact(
                    control_class=control_class,
                    path=str(path),
                    sha256=_sha256(content),
                    coverage=float(mask.sum()) / total,
                )
            )
        guide_content = _neutral_structure_guide(base, edges)
        guide_path = view_directory / "structure_guide.png"
        atomic_write(guide_path, guide_content)
        manifest = ControlPackManifest(
            view_id=view_directory.name,
            width=policy.shape[1],
            height=policy.shape[0],
            policy_source_ref=str(policy_path),
            critical_edge_ref=str(edge_path),
            structure_guide_ref=str(guide_path),
            structure_guide_sha256=_sha256(guide_content),
            masks=tuple(artifacts),
            overlap_pixels=overlap,
            uncovered_pixels=uncovered,
        )
        atomic_write(
            view_directory / "control_pack_manifest.json",
            manifest.model_dump_json(indent=2).encode("utf-8") + b"\n",
        )
        _write_layer_authority_artifacts(
            view_directory,
            size=(policy.shape[1], policy.shape[0]),
            edge_band=edge_band,
        )
        return manifest
