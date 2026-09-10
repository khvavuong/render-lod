"""Fail-closed compositing that prevents generative edits in LOCKED pixels."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
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


class ProtectRefinement:
    """Restore authoritative PBR pixels under each view's LOCKED mask."""

    def execute(
        self,
        render_root: Path,
        generated_root: Path,
        *,
        minimum_edge_alignment: float = 0.75,
    ) -> ProtectedRefinementArtifacts:
        if not 0.0 <= minimum_edge_alignment <= 1.0:
            raise ValueError("minimum_edge_alignment must be between zero and one")
        evidence: list[dict[str, object]] = []
        for view_dir in sorted(path for path in generated_root.glob("view-*") if path.is_dir()):
            candidates = tuple(path for path in view_dir.glob("refined.*") if path.is_file())
            if len(candidates) != 1:
                raise InvalidModelError(f"{view_dir.name} must contain exactly one refined image")
            refined = candidates[0]
            base = render_root / view_dir.name / "base_rgb.png"
            mask = render_root / view_dir.name / "locked_mask.png"
            critical_edges = render_root / view_dir.name / "edges.png"
            control_manifest = render_root / view_dir.name / "control_pack_manifest.json"
            if not all(
                path.is_file() for path in (base, mask, critical_edges, control_manifest)
            ):
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
            edge_alignment = self._edge_alignment(
                generated_rgb,
                critical_edges,
                locked,
            )
            accepted = edge_alignment >= minimum_edge_alignment
            generation_manifest = view_dir / "generation_manifest.json"
            document = json.loads(generation_manifest.read_text(encoding="utf-8"))
            if not accepted:
                document["output"].update(
                    {
                        "protected_composite": False,
                        "geometry_protection_status": "rejected_edge_misalignment",
                        "edge_alignment_recall": edge_alignment,
                        "edge_alignment_threshold": minimum_edge_alignment,
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
                        edge_alignment=edge_alignment,
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
                    "provider_source_ref": str(provider_source),
                    "locked_mask_ref": str(mask),
                    "locked_mask_sha256": _sha256(mask),
                    "base_rgb_sha256": _sha256(base),
                    "geometry_protection_status": "promoted",
                    "edge_alignment_recall": edge_alignment,
                    "edge_alignment_threshold": minimum_edge_alignment,
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
                    edge_alignment=edge_alignment,
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
    def _edge_alignment(
        generated: Image.Image,
        critical_edge_path: Path,
        locked_mask: Image.Image,
    ) -> float:
        with Image.open(critical_edge_path) as source:
            critical = np.asarray(
                source.convert("L").resize(generated.size, Image.Resampling.NEAREST),
                dtype=np.uint8,
            ) >= 240
        locked = np.asarray(locked_mask, dtype=np.uint8) >= 128
        authoritative = critical & locked
        total = int(np.count_nonzero(authoritative))
        if not total:
            return 1.0
        generated_edges = generated.convert("L").filter(ImageFilter.FIND_EDGES)
        nearby = np.asarray(
            generated_edges.filter(ImageFilter.MaxFilter(3)), dtype=np.uint8
        ) >= 64
        return float(np.count_nonzero(authoritative & nearby)) / total

    @staticmethod
    def _evidence(
        view_id: str,
        base: Path,
        mask: Path,
        provider_source: Path,
        output: Path,
        *,
        accepted: bool,
        edge_alignment: float,
    ) -> dict[str, object]:
        return {
            "view_id": view_id,
            "accepted": accepted,
            "edge_alignment_recall": edge_alignment,
            "base_rgb": str(base),
            "base_rgb_sha256": _sha256(base),
            "locked_mask": str(mask),
            "locked_mask_sha256": _sha256(mask),
            "provider_source": str(provider_source),
            "provider_source_sha256": _sha256(provider_source),
            "protected_output": str(output) if accepted else None,
            "output_sha256": _sha256(output),
        }
