"""Retrofit or refresh branding on a complete set of existing deliverables."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from v365_archviz.application.brand_watermark import BrandWatermark
from v365_archviz.artifacts import atomic_write
from v365_archviz.errors import InvalidModelError


@dataclass(frozen=True, slots=True)
class BrandedDeliverables:
    image_paths: tuple[Path, ...]
    board_path: Path | None
    video_path: Path | None
    manifest_path: Path


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _preserved_source(output: Path, source_name: str) -> Path:
    source = output.with_name(source_name)
    if not source.is_file():
        atomic_write(source, output.read_bytes())
    return source


class BrandDeliverables:
    def execute(
        self,
        watermark: BrandWatermark,
        generated_root: Path,
        *,
        board_path: Path | None = None,
        video_path: Path | None = None,
    ) -> BrandedDeliverables:
        if not generated_root.is_dir():
            raise InvalidModelError(f"generated root does not exist: {generated_root}")
        branded_images: list[Path] = []
        for view_dir in sorted(generated_root.glob("view-*")):
            candidates = sorted(view_dir.glob("refined.*"))
            if len(candidates) != 1:
                raise InvalidModelError(f"expected one refined image in {view_dir}")
            output = candidates[0]
            source = _preserved_source(output, f"provider_source{output.suffix}")
            watermark.apply_image(source, output)
            generation_manifest_path = view_dir / "generation_manifest.json"
            if generation_manifest_path.is_file():
                generation_manifest = json.loads(
                    generation_manifest_path.read_text(encoding="utf-8")
                )
                if not isinstance(generation_manifest, dict):
                    raise InvalidModelError(
                        f"invalid generation manifest: {generation_manifest_path}"
                    )
                output_metadata = generation_manifest.get("output")
                if not isinstance(output_metadata, dict):
                    output_metadata = {}
                    generation_manifest["output"] = output_metadata
                output_metadata["provider_source_sha256"] = _sha256(source)
                output_metadata["sha256"] = _sha256(output)
                output_metadata["brand_watermark"] = True
                atomic_write(
                    generation_manifest_path,
                    json.dumps(generation_manifest, ensure_ascii=False, indent=2).encode() + b"\n",
                )
            branded_images.append(output)

        board_candidate = board_path or generated_root / "viewset_board.jpg"
        resolved_board: Path | None
        if board_candidate.is_file():
            resolved_board = board_candidate
            board_source = _preserved_source(resolved_board, f"unbranded_{resolved_board.name}")
            watermark.apply_image(board_source, resolved_board)
        else:
            resolved_board = None

        if video_path is not None:
            if not video_path.is_file():
                raise InvalidModelError(f"video deliverable does not exist: {video_path}")
            video_source = _preserved_source(video_path, f"unbranded_{video_path.name}")
            watermark.apply_video(video_source, video_path)

        manifest_path = generated_root / "branding_manifest.json"
        manifest = {
            "schema_version": "1.0.0",
            "logo_ref": str(watermark.logo_path),
            "logo_sha256": _sha256(watermark.logo_path),
            "opacity": watermark.opacity,
            "width_ratio": watermark.width_ratio,
            "margin_ratio": watermark.margin_ratio,
            "position": "top-left",
            "images": [{"path": str(path), "sha256": _sha256(path)} for path in branded_images],
            "board": (
                {"path": str(resolved_board), "sha256": _sha256(resolved_board)}
                if resolved_board is not None
                else None
            ),
            "video": (
                {"path": str(video_path), "sha256": _sha256(video_path)}
                if video_path is not None
                else None
            ),
        }
        atomic_write(
            manifest_path,
            json.dumps(manifest, ensure_ascii=False, indent=2).encode() + b"\n",
        )
        return BrandedDeliverables(
            image_paths=tuple(branded_images),
            board_path=resolved_board,
            video_path=video_path,
            manifest_path=manifest_path,
        )
