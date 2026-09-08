"""Validate the integrity and traceability of a generated view set."""

from __future__ import annotations

import hashlib
import json
import mimetypes
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, UnidentifiedImageError

from v365_archviz.artifacts import atomic_write
from v365_archviz.domain.design import DesignDNA
from v365_archviz.domain.workflow import ViewSet
from v365_archviz.errors import InvalidModelError


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _aspect_ratio(value: str) -> float:
    width, height = value.split(":", maxsplit=1)
    return int(width) / int(height)


@dataclass(frozen=True, slots=True)
class ViewSetValidationArtifacts:
    report_path: Path
    passed: bool
    error_count: int


class ValidateGeneratedViewSet:
    """Run deterministic checks; visual design conformance remains a human gate."""

    def execute(
        self,
        render_root: Path,
        generated_root: Path,
        view_set_path: Path,
        design_dna_path: Path,
        output_path: Path | None = None,
        minimum_width: int = 1024,
        minimum_height: int = 576,
    ) -> ViewSetValidationArtifacts:
        try:
            view_set = ViewSet.model_validate_json(view_set_path.read_text(encoding="utf-8"))
            design = DesignDNA.model_validate_json(design_dna_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise InvalidModelError(f"cannot load QA contracts: {exc}") from exc

        views: list[dict[str, Any]] = []
        output_hashes: list[str] = []
        reference_signatures: list[tuple[tuple[str, str], ...]] = []
        for camera in view_set.cameras:
            findings: list[dict[str, str]] = []
            manifest_path = generated_root / camera.view_id / "generation_manifest.json"
            manifest: dict[str, Any] = {}
            if not manifest_path.is_file():
                findings.append(self._finding("error", "manifest_missing", str(manifest_path)))
            else:
                try:
                    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError) as exc:
                    findings.append(self._finding("error", "manifest_invalid", str(exc)))

            if manifest:
                self._check_equal(findings, "view_id", manifest.get("view_id"), camera.view_id)
                self._check_equal(
                    findings, "project_id", manifest.get("project_id"), design.project_id
                )
                self._check_equal(
                    findings,
                    "design_revision",
                    manifest.get("design_revision"),
                    design.design_revision,
                )
                self._check_equal(
                    findings,
                    "view_set_revision",
                    view_set.design_revision,
                    design.design_revision,
                )

            input_hashes = manifest.get("inputs", {}) if manifest else {}
            for name in ("base_rgb", "depth", "instance_id", "semantic", "edges"):
                input_path = render_root / camera.view_id / f"{name}.png"
                if not input_path.is_file():
                    findings.append(self._finding("error", "input_missing", str(input_path)))
                elif input_hashes.get(name) != _sha256(input_path):
                    findings.append(self._finding("error", "input_hash_mismatch", input_path.name))

            image_path = self._find_output(generated_root / camera.view_id)
            dimensions: list[int] | None = None
            if image_path is None:
                findings.append(self._finding("error", "output_missing", camera.view_id))
            else:
                try:
                    with Image.open(image_path) as image:
                        image.load()
                        dimensions = [image.width, image.height]
                        detected_media_type = Image.MIME.get(image.format or "")
                except (UnidentifiedImageError, OSError) as exc:
                    findings.append(self._finding("error", "output_invalid", str(exc)))
                else:
                    expected_output = manifest.get("output", {}) if manifest else {}
                    output_hash = _sha256(image_path)
                    output_hashes.append(output_hash)
                    if output_hash != expected_output.get("sha256"):
                        findings.append(
                            self._finding("error", "output_hash_mismatch", image_path.name)
                        )
                    if detected_media_type != expected_output.get("media_type"):
                        findings.append(
                            self._finding(
                                "error",
                                "output_media_type_mismatch",
                                f"detected {detected_media_type}",
                            )
                        )
                    if image.width < minimum_width or image.height < minimum_height:
                        findings.append(
                            self._finding(
                                "error",
                                "output_too_small",
                                f"{image.width}x{image.height}",
                            )
                        )
                    expected_ratio = _aspect_ratio(camera.aspect_ratio)
                    if abs(image.width / image.height - expected_ratio) > 0.02:
                        findings.append(
                            self._finding(
                                "error",
                                "aspect_ratio_mismatch",
                                f"expected {camera.aspect_ratio}, got {image.width}:{image.height}",
                            )
                        )

            references = tuple(
                sorted(
                    (name, value)
                    for name, value in input_hashes.items()
                    if name.startswith("reference_")
                )
            )
            reference_signatures.append(references)
            views.append(
                {
                    "view_id": camera.view_id,
                    "role": camera.role.value,
                    "technical_status": (
                        "pass"
                        if not any(item["severity"] == "error" for item in findings)
                        else "fail"
                    ),
                    "image": str(image_path) if image_path else None,
                    "dimensions": dimensions,
                    "findings": findings,
                }
            )

        global_findings: list[dict[str, str]] = []
        if len(output_hashes) != len(set(output_hashes)):
            global_findings.append(
                self._finding("error", "duplicate_outputs", "generated views must be unique")
            )
        if reference_signatures and len(set(reference_signatures)) != 1:
            global_findings.append(
                self._finding(
                    "error",
                    "inconsistent_references",
                    "all views in one view set must use the same references",
                )
            )

        error_count = sum(
            item["severity"] == "error" for view in views for item in view["findings"]
        ) + sum(item["severity"] == "error" for item in global_findings)
        report = {
            "schema_version": "1.0.0",
            "scope": "technical_artifact_integrity",
            "project_id": design.project_id,
            "design_revision": design.design_revision,
            "passed": error_count == 0,
            "error_count": error_count,
            "global_findings": global_findings,
            "views": views,
            "human_review_required": True,
            "human_review_note": (
                "A technical pass does not certify geometry or design conformance. "
                "Compare every generated view with its base RGB, depth, edges, and approved brief."
            ),
        }
        target = output_path or generated_root / "technical_qa.json"
        atomic_write(
            target,
            json.dumps(report, ensure_ascii=False, indent=2).encode("utf-8") + b"\n",
        )
        return ViewSetValidationArtifacts(target, error_count == 0, error_count)

    @staticmethod
    def _finding(severity: str, code: str, message: str) -> dict[str, str]:
        return {"severity": severity, "code": code, "message": message}

    @staticmethod
    def _check_equal(
        findings: list[dict[str, str]], code: str, actual: object, expected: object
    ) -> None:
        if actual != expected:
            findings.append(
                ValidateGeneratedViewSet._finding(
                    "error", f"{code}_mismatch", f"expected {expected!r}, got {actual!r}"
                )
            )

    @staticmethod
    def _find_output(view_directory: Path) -> Path | None:
        candidates = sorted(
            path
            for path in view_directory.glob("refined.*")
            if path.is_file() and (mimetypes.guess_type(path.name)[0] or "").startswith("image/")
        )
        return candidates[0] if len(candidates) == 1 else None
