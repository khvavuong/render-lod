"""Promote a human-approved view set into reusable, geometry-safe quality references."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

from PIL import Image, UnidentifiedImageError

from v365_archviz.artifacts import atomic_write
from v365_archviz.errors import InvalidModelError


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


@dataclass(frozen=True, slots=True)
class QualityBaselineArtifacts:
    manifest_path: Path
    baseline_id: str
    reference_ids: dict[str, str]


class PromoteQualityBaseline:
    """Store approved site/facade masters as style-only references for future jobs."""

    _ROLE_BY_MASTER: ClassVar[dict[str, str]] = {
        "site": "context_realism_reference",
        "facade": "factory_design_reference",
    }
    _ALLOWED_BY_ROLE: ClassVar[dict[str, tuple[str, ...]]] = {
        "context_realism_reference": ("industrial_context", "roads", "atmosphere"),
        "factory_design_reference": (
            "construction_detail",
            "material_response",
            "human_scale",
        ),
    }

    def execute(
        self,
        artifact_dir: Path,
        model_revision: str,
        design_revision: str,
        view_set_id: str,
    ) -> QualityBaselineArtifacts:
        generated_root = artifact_dir / "generated" / model_revision / design_revision
        review_path = generated_root / "design_master_review.json"
        try:
            review: dict[str, Any] = json.loads(review_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise InvalidModelError("approved Design Master evidence is missing") from exc
        if not review.get("approved"):
            raise InvalidModelError("Design Masters must be approved before baseline promotion")
        if review.get("view_set_id") not in {None, view_set_id}:
            raise InvalidModelError("Design Masters belong to a different view set")
        final_review_path = generated_root / "final_viewset_review.json"
        try:
            final_review = json.loads(final_review_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise InvalidModelError("final visual approval is missing") from exc
        if not final_review.get("approved"):
            raise InvalidModelError("final visual approval is required for baseline promotion")
        if final_review.get("view_set_id") not in {None, view_set_id}:
            raise InvalidModelError("final visual approval belongs to a different view set")

        master_view_ids = review.get("master_view_ids", {})
        if not isinstance(master_view_ids, dict):
            raise InvalidModelError("Design Master view mapping is invalid")

        reference_ids: dict[str, str] = {}
        source_views: dict[str, str] = {}
        for master_name, role in self._ROLE_BY_MASTER.items():
            view_id = master_view_ids.get(master_name)
            if not isinstance(view_id, str):
                raise InvalidModelError(f"approved {master_name} master is missing")
            source = generated_root / view_id / "unbranded_refined.jpg"
            if not source.is_file():
                source = generated_root / view_id / "refined.jpg"
            reference_ids[role] = self._store_reference(
                artifact_dir,
                source,
                role,
                view_set_id,
                view_id,
            )
            source_views[role] = view_id

        board_path = generated_root / "viewset_board.jpg"
        identity = json.dumps(
            {
                "model_revision": model_revision,
                "design_revision": design_revision,
                "view_set_id": view_set_id,
                "reference_ids": reference_ids,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        baseline_id = hashlib.sha256(identity).hexdigest()[:16]
        manifest = {
            "schema_version": "1.0.0",
            "baseline_id": baseline_id,
            "status": "active",
            "source": {
                "model_revision": model_revision,
                "design_revision": design_revision,
                "view_set_id": view_set_id,
                "master_views": source_views,
            },
            "reference_ids": reference_ids,
            "influence_contract": {
                "allowed": [
                    "industrial_context_realism",
                    "facade_detail_quality",
                    "material_response",
                    "natural_daylight",
                ],
                "prohibited": ["project_geometry", "camera", "palette", "logo"],
            },
            "board": (
                {"path": str(board_path), "sha256": _sha256_bytes(board_path.read_bytes())}
                if board_path.is_file()
                else None
            ),
        }
        manifest_path = artifact_dir / "quality_baselines" / "active.json"
        atomic_write(
            manifest_path,
            json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8") + b"\n",
        )
        return QualityBaselineArtifacts(manifest_path, baseline_id, reference_ids)

    def _store_reference(
        self,
        artifact_dir: Path,
        source: Path,
        role: str,
        view_set_id: str,
        view_id: str,
    ) -> str:
        try:
            content = source.read_bytes()
            with Image.open(source) as image:
                width, height = image.size
                image_format = (image.format or "jpeg").lower()
        except (OSError, UnidentifiedImageError) as exc:
            raise InvalidModelError(f"approved master image is invalid: {source}") from exc
        suffix = {"jpeg": ".jpg", "png": ".png", "webp": ".webp"}.get(image_format)
        if suffix is None:
            raise InvalidModelError(f"unsupported approved master format: {image_format}")
        content_sha = _sha256_bytes(content)
        reference_id = hashlib.sha256(f"{role}\n{content_sha}".encode()).hexdigest()
        root = artifact_dir / "references" / reference_id
        stored_name = f"source{suffix}"
        atomic_write(root / stored_name, content)
        metadata = {
            "schema_version": "1.0.0",
            "reference_id": reference_id,
            "role": role,
            "file_name": source.name,
            "stored_name": stored_name,
            "content_sha256": content_sha,
            "width": width,
            "height": height,
            "allowed_influence": list(self._ALLOWED_BY_ROLE[role]),
            "prohibited_influence": ["project_geometry", "camera", "palette", "logo"],
            "source": "approved_viewset_baseline",
            "source_view_set_id": view_set_id,
            "source_view_id": view_id,
        }
        atomic_write(
            root / "metadata.json",
            json.dumps(metadata, ensure_ascii=False, indent=2).encode("utf-8") + b"\n",
        )
        return reference_id
