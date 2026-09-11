"""Fail-closed compositing that prevents generative edits in LOCKED pixels."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from numpy.typing import NDArray
from PIL import Image, ImageFilter

from v365_archviz.artifacts import atomic_write
from v365_archviz.errors import InvalidModelError


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass(frozen=True, slots=True)
class ProtectedRefinementArtifacts:
    view_count: int
    promoted_count: int
    rejected_count: int
    manifest_path: Path


@dataclass(frozen=True, slots=True)
class EdgeGeometryMetrics:
    recall: float
    precision: float
    f1: float
    bidirectional_chamfer_px: float


class ProtectRefinement:
    """Screen geometry and optionally restore authoritative pixels under LOCKED masks."""

    def execute(
        self,
        render_root: Path,
        generated_root: Path,
        *,
        minimum_edge_alignment: float = 0.75,
        minimum_edge_f1: float = 0.80,
        maximum_edge_chamfer_px: float = 3.0,
        restore_locked_pixels: bool = True,
    ) -> ProtectedRefinementArtifacts:
        if not 0.0 <= minimum_edge_alignment <= 1.0:
            raise ValueError("minimum_edge_alignment must be between zero and one")
        if not 0.0 <= minimum_edge_f1 <= 1.0:
            raise ValueError("minimum_edge_f1 must be between zero and one")
        if maximum_edge_chamfer_px < 0:
            raise ValueError("maximum_edge_chamfer_px must be non-negative")
        evidence: list[dict[str, object]] = []
        for view_dir in sorted(path for path in generated_root.glob("view-*") if path.is_dir()):
            candidates = tuple(path for path in view_dir.glob("refined.*") if path.is_file())
            if len(candidates) != 1:
                raise InvalidModelError(f"{view_dir.name} must contain exactly one refined image")
            refined = candidates[0]
            base = render_root / view_dir.name / "base_rgb.png"
            mask = render_root / view_dir.name / "locked_mask.png"
            critical_edges = render_root / view_dir.name / "edges.png"
            semantic = render_root / view_dir.name / "semantic.png"
            control_manifest = render_root / view_dir.name / "control_pack_manifest.json"
            if not all(path.is_file() for path in (base, mask, critical_edges, control_manifest)):
                raise InvalidModelError(f"{view_dir.name} has no complete protected control pack")

            provider_source = view_dir / f"provider_source{refined.suffix.lower()}"
            if provider_source != refined:
                atomic_write(provider_source, refined.read_bytes())
            with Image.open(refined) as generated_image:
                target_size = generated_image.size
                generated_rgb = generated_image.convert("RGB")
            with Image.open(base) as base_image:
                authoritative = base_image.convert("RGB").resize(
                    target_size, Image.Resampling.LANCZOS
                )
            with Image.open(mask) as mask_image:
                locked = mask_image.convert("L").resize(target_size, Image.Resampling.NEAREST)
            edge_metrics = self._edge_geometry_metrics(
                generated_rgb,
                critical_edges,
                locked,
                semantic_path=semantic if semantic.is_file() else None,
            )
            accepted = (
                edge_metrics.recall >= minimum_edge_alignment
                and edge_metrics.f1 >= minimum_edge_f1
                and edge_metrics.bidirectional_chamfer_px <= maximum_edge_chamfer_px
            )
            generation_manifest = view_dir / "generation_manifest.json"
            document = json.loads(generation_manifest.read_text(encoding="utf-8"))
            if not accepted:
                document["output"].update(
                    {
                        "protected_composite": False,
                        "geometry_protection_mode": (
                            "pixel_restore" if restore_locked_pixels else "validation_only"
                        ),
                        "geometry_protection_status": (
                            "rejected_edge_misalignment"
                            if restore_locked_pixels
                            else "review_edge_misalignment"
                        ),
                        **self._metrics_document(edge_metrics),
                        "edge_alignment_threshold": minimum_edge_alignment,
                        "edge_f1_threshold": minimum_edge_f1,
                        "edge_chamfer_threshold_px": maximum_edge_chamfer_px,
                        "provider_source_ref": str(provider_source),
                        "locked_mask_ref": str(mask),
                        "locked_mask_sha256": _sha256(mask),
                        "base_rgb_sha256": _sha256(base),
                    }
                )
                atomic_write(
                    generation_manifest,
                    json.dumps(document, ensure_ascii=False, indent=2).encode("utf-8") + b"\n",
                )
                evidence.append(
                    self._evidence(
                        view_dir.name,
                        base,
                        mask,
                        provider_source,
                        refined,
                        accepted=False,
                        edge_metrics=edge_metrics,
                        protection_mode=(
                            "pixel_restore" if restore_locked_pixels else "validation_only"
                        ),
                    )
                )
                continue
            if not restore_locked_pixels:
                document["output"].update(
                    {
                        "protected_composite": False,
                        "geometry_protection_mode": "validation_only",
                        "geometry_protection_status": "edge_alignment_screen_passed",
                        **self._metrics_document(edge_metrics),
                        "edge_alignment_threshold": minimum_edge_alignment,
                        "edge_f1_threshold": minimum_edge_f1,
                        "edge_chamfer_threshold_px": maximum_edge_chamfer_px,
                        "provider_source_ref": str(provider_source),
                        "locked_mask_ref": str(mask),
                        "locked_mask_sha256": _sha256(mask),
                        "base_rgb_sha256": _sha256(base),
                        "sha256": _sha256(refined),
                    }
                )
                atomic_write(
                    generation_manifest,
                    json.dumps(document, ensure_ascii=False, indent=2).encode("utf-8") + b"\n",
                )
                evidence.append(
                    self._evidence(
                        view_dir.name,
                        base,
                        mask,
                        provider_source,
                        refined,
                        accepted=True,
                        edge_metrics=edge_metrics,
                        protection_mode="validation_only",
                    )
                )
                continue
            protected = Image.composite(authoritative, generated_rgb, locked)
            from io import BytesIO

            buffer = BytesIO()
            protected.save(buffer, format="PNG", optimize=True)
            protected_path = view_dir / "refined.png"
            atomic_write(protected_path, buffer.getvalue())
            if refined != protected_path:
                refined.unlink(missing_ok=True)

            document["output"].update(
                {
                    "media_type": "image/png",
                    "sha256": _sha256(protected_path),
                    "protected_composite": True,
                    "geometry_protection_mode": "pixel_restore",
                    "provider_source_ref": str(provider_source),
                    "locked_mask_ref": str(mask),
                    "locked_mask_sha256": _sha256(mask),
                    "base_rgb_sha256": _sha256(base),
                    "geometry_protection_status": "promoted",
                    **self._metrics_document(edge_metrics),
                    "edge_alignment_threshold": minimum_edge_alignment,
                    "edge_f1_threshold": minimum_edge_f1,
                    "edge_chamfer_threshold_px": maximum_edge_chamfer_px,
                }
            )
            atomic_write(
                generation_manifest,
                json.dumps(document, ensure_ascii=False, indent=2).encode("utf-8") + b"\n",
            )
            evidence.append(
                self._evidence(
                    view_dir.name,
                    base,
                    mask,
                    provider_source,
                    protected_path,
                    accepted=True,
                    edge_metrics=edge_metrics,
                    protection_mode="pixel_restore",
                )
            )
        if not evidence:
            raise InvalidModelError("no generated views found for protected compositing")
        manifest_path = generated_root / "protected_composite_manifest.json"
        atomic_write(
            manifest_path,
            json.dumps(
                {"schema_version": "1.0.0", "views": evidence},
                ensure_ascii=False,
                indent=2,
            ).encode("utf-8")
            + b"\n",
        )
        promoted = sum(bool(item["accepted"]) for item in evidence)
        return ProtectedRefinementArtifacts(
            len(evidence), promoted, len(evidence) - promoted, manifest_path
        )

    @staticmethod
    def _edge_geometry_metrics(
        generated: Image.Image,
        critical_edge_path: Path,
        locked_mask: Image.Image,
        *,
        semantic_path: Path | None = None,
    ) -> EdgeGeometryMetrics:
        with Image.open(critical_edge_path) as source:
            critical = (
                np.asarray(
                    source.convert("L").resize(generated.size, Image.Resampling.NEAREST),
                    dtype=np.uint8,
                )
                >= 240
            )
        locked = np.asarray(locked_mask, dtype=np.uint8) >= 128
        if semantic_path is not None:
            authoritative = (
                ProtectRefinement._semantic_boundaries(semantic_path, generated.size) & locked
            )
            if not np.any(authoritative):
                authoritative = critical & locked
        else:
            authoritative = critical & locked
        generated_edges = (
            np.asarray(generated.convert("L").filter(ImageFilter.FIND_EDGES), dtype=np.uint8) >= 64
        ) & locked
        authoritative_count = int(np.count_nonzero(authoritative))
        if not authoritative_count:
            return EdgeGeometryMetrics(1.0, 1.0, 1.0, 0.0)
        # Ignore texture edges far from authored structural boundaries. They are allowed
        # photoreal detail and must not be counted as invented geometry.
        generated_edges &= ProtectRefinement._dilate(authoritative, 8)
        generated_count = int(np.count_nonzero(generated_edges))
        # Express alignment tolerance in image space, not a fixed preview-era pixel count.
        # At 2K a four-pixel band is ~0.26% of frame height and absorbs antialiasing plus
        # profiled-metal micro-edges without forgiving a moved door, wall or roof silhouette.
        alignment_tolerance = max(3, round(min(generated.size) * 0.0025))
        generated_nearby = ProtectRefinement._dilate(generated_edges, alignment_tolerance)
        authoritative_nearby = ProtectRefinement._dilate(authoritative, alignment_tolerance)
        recall = float(np.count_nonzero(authoritative & generated_nearby)) / authoritative_count
        precision = (
            float(np.count_nonzero(generated_edges & authoritative_nearby)) / generated_count
            if generated_count
            else 0.0
        )
        f1 = 2.0 * precision * recall / (precision + recall) if precision + recall else 0.0
        chamfer = 0.5 * (
            ProtectRefinement._mean_capped_edge_distance(authoritative, generated_edges)
            + ProtectRefinement._mean_capped_edge_distance(generated_edges, authoritative)
        )
        return EdgeGeometryMetrics(recall, precision, f1, chamfer)

    @staticmethod
    def _semantic_boundaries(
        semantic_path: Path,
        target_size: tuple[int, int],
        *,
        color_delta: int = 20,
    ) -> NDArray[np.bool_]:
        with Image.open(semantic_path) as source:
            semantic = np.asarray(
                source.convert("RGB").resize(target_size, Image.Resampling.NEAREST),
                dtype=np.int16,
            )
        boundary = np.zeros(semantic.shape[:2], dtype=np.bool_)
        horizontal = np.max(np.abs(semantic[:, 1:] - semantic[:, :-1]), axis=2) >= color_delta
        vertical = np.max(np.abs(semantic[1:, :] - semantic[:-1, :]), axis=2) >= color_delta
        boundary[:, 1:] |= horizontal
        boundary[:, :-1] |= horizontal
        boundary[1:, :] |= vertical
        boundary[:-1, :] |= vertical
        return boundary

    @staticmethod
    def _edge_alignment(
        generated: Image.Image,
        critical_edge_path: Path,
        locked_mask: Image.Image,
    ) -> float:
        """Compatibility accessor retained for callers of the v1 metric."""

        return ProtectRefinement._edge_geometry_metrics(
            generated, critical_edge_path, locked_mask
        ).recall

    @staticmethod
    def _dilate(mask: NDArray[np.bool_], radius: int) -> NDArray[np.bool_]:
        if radius <= 0:
            return mask.copy()
        image = Image.fromarray(mask.astype(np.uint8) * 255, mode="L")
        return np.asarray(image.filter(ImageFilter.MaxFilter(radius * 2 + 1))) >= 128

    @staticmethod
    def _mean_capped_edge_distance(
        source: NDArray[np.bool_],
        target: NDArray[np.bool_],
        *,
        maximum_distance: int = 8,
    ) -> float:
        source_count = int(np.count_nonzero(source))
        if not source_count:
            return 0.0
        if not np.any(target):
            return float(maximum_distance + 1)
        distances = np.full(source.shape, maximum_distance + 1, dtype=np.uint8)
        expanded = target.copy()
        unresolved = source.copy()
        for distance in range(maximum_distance + 1):
            reached = unresolved & expanded
            distances[reached] = distance
            unresolved &= ~reached
            if not np.any(unresolved):
                break
            expanded = ProtectRefinement._dilate(expanded, 1)
        return float(distances[source].mean())

    @staticmethod
    def _metrics_document(metrics: EdgeGeometryMetrics) -> dict[str, float]:
        return {
            "edge_alignment_recall": metrics.recall,
            "edge_alignment_precision": metrics.precision,
            "edge_alignment_f1": metrics.f1,
            "edge_bidirectional_chamfer_px": metrics.bidirectional_chamfer_px,
        }

    @staticmethod
    def _evidence(
        view_id: str,
        base: Path,
        mask: Path,
        provider_source: Path,
        output: Path,
        *,
        accepted: bool,
        edge_metrics: EdgeGeometryMetrics,
        protection_mode: str = "pixel_restore",
    ) -> dict[str, object]:
        return {
            "view_id": view_id,
            "accepted": accepted,
            "protection_mode": protection_mode,
            **ProtectRefinement._metrics_document(edge_metrics),
            "base_rgb": str(base),
            "base_rgb_sha256": _sha256(base),
            "locked_mask": str(mask),
            "locked_mask_sha256": _sha256(mask),
            "provider_source": str(provider_source),
            "provider_source_sha256": _sha256(provider_source),
            "protected_output": str(output) if accepted else None,
            "output_sha256": _sha256(output),
        }
