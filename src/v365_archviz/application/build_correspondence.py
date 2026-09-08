"""Build visibility and cross-view identity indexes from deterministic ID passes."""

from __future__ import annotations

import json
import math
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from PIL import Image

from v365_archviz.artifacts import atomic_write
from v365_archviz.domain.scene import CanonicalScene
from v365_archviz.domain.workflow import ViewSet
from v365_archviz.errors import InvalidModelError


@dataclass(frozen=True, slots=True)
class CorrespondenceArtifacts:
    manifest_path: Path
    visibility_paths: tuple[Path, ...]
    pair_count: int


def _srgb_to_byte(value: int) -> int:
    encoded = value / 255
    linear = encoded / 12.92 if encoded <= 0.04045 else ((encoded + 0.055) / 1.055) ** 2.4
    return round(linear * 255)


def _decode_id(color: tuple[int, int, int]) -> int:
    red, green, blue = (_srgb_to_byte(value) for value in color)
    return red | (green << 8) | (blue << 16)


class BuildCorrespondenceIndex:
    """Persist exact shared object identities; pixel reprojection can build on this index."""

    def execute(
        self,
        scene_path: Path,
        view_set_path: Path,
        render_root: Path,
        minimum_pixels: int = 16,
    ) -> CorrespondenceArtifacts:
        scene = CanonicalScene.model_validate_json(scene_path.read_text(encoding="utf-8"))
        view_set = ViewSet.model_validate_json(view_set_path.read_text(encoding="utf-8"))
        element_by_index = {
            index: element for index, element in enumerate(scene.elements, start=1)
        }
        surfaces_by_element: dict[str, list[str]] = {}
        for surface in scene.surfaces:
            surfaces_by_element.setdefault(surface.element_id, []).append(surface.surface_id)

        visibility_paths: list[Path] = []
        visible_by_view: dict[str, set[str]] = {}
        for camera in view_set.cameras:
            image_path = render_root / camera.view_id / "instance_id.png"
            if not image_path.is_file():
                raise InvalidModelError(f"instance ID pass not found: {image_path}")
            with Image.open(image_path) as image:
                rgb = image.convert("RGB")
                pixels = cast(Iterable[tuple[int, int, int]], rgb.getdata())
                counts = Counter(_decode_id(color) for color in pixels)
                pixel_count = rgb.width * rgb.height
            visible = []
            visible_ids: set[str] = set()
            for pass_index, count in counts.most_common():
                element = element_by_index.get(pass_index)
                if element is None or count < minimum_pixels:
                    continue
                visible_ids.add(element.scene_element_id)
                visible.append(
                    {
                        "scene_element_id": element.scene_element_id,
                        "source_external_id": element.source.external_id,
                        "semantic_role": element.semantic_role.value,
                        "pixel_count": count,
                        "coverage": count / pixel_count,
                        "surface_ids": sorted(
                            surfaces_by_element.get(element.scene_element_id, ())
                        ),
                    }
                )
            visible_by_view[camera.view_id] = visible_ids
            visibility_path = render_root / camera.view_id / "visibility.json"
            atomic_write(
                visibility_path,
                json.dumps(
                    {
                        "schema_version": "1.0.0",
                        "view_id": camera.view_id,
                        "camera_ref": str(render_root / camera.view_id / "camera.json"),
                        "instance_id_ref": str(image_path),
                        "visible_elements": visible,
                    },
                    ensure_ascii=False,
                    indent=2,
                ).encode()
                + b"\n",
            )
            visibility_paths.append(visibility_path)

        pairs = []
        cameras = view_set.cameras
        for left_index, left in enumerate(cameras):
            for right in cameras[left_index + 1 :]:
                shared = sorted(
                    visible_by_view[left.view_id] & visible_by_view[right.view_id]
                )
                shared_surfaces = sorted(
                    {
                        surface_id
                        for element_id in shared
                        for surface_id in surfaces_by_element.get(element_id, ())
                    }
                )
                pairs.append(
                    {
                        "view_a": left.view_id,
                        "view_b": right.view_id,
                        "shared_element_ids": shared,
                        "shared_surface_ids": shared_surfaces,
                    }
                )
        manifest_path = render_root / "correspondence_index.json"
        atomic_write(
            manifest_path,
            json.dumps(
                {
                    "schema_version": "1.0.0",
                    "kind": "identity_visibility_index",
                    "design_revision": view_set.design_revision,
                    "views": [camera.view_id for camera in cameras],
                    "pairs": pairs,
                    "pixel_reprojection_maps_available": False,
                    "note": (
                        "This index proves shared world-space identities and visibility. "
                        "Dense pixel reprojection requires metric depth maps."
                    ),
                },
                ensure_ascii=False,
                indent=2,
            ).encode()
            + b"\n",
        )
        return CorrespondenceArtifacts(
            manifest_path=manifest_path,
            visibility_paths=tuple(visibility_paths),
            pair_count=math.comb(len(cameras), 2),
        )
