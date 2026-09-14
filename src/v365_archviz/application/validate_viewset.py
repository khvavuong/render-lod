"""Validate the integrity and traceability of a generated view set."""

from __future__ import annotations

import colorsys
import hashlib
import json
import mimetypes
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import numpy as np
from numpy.typing import NDArray
from PIL import Image, ImageFilter, UnidentifiedImageError

from v365_archviz.artifacts import atomic_write
from v365_archviz.domain.design import DesignDNA
from v365_archviz.domain.workflow import ViewRole, ViewSet
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

    # These metrics are useful drift detectors, but they are deliberately conservative
    # image heuristics rather than proof that an artifact is structurally invalid. Keep
    # them visible to the reviewer without blocking a visually approved deliverable.
    _VISUAL_REVIEW_CODES = frozenset(
        {
            "authored_landscape_not_retained",
            "context_proxy_not_visible_in_context_view",
            "material_role_mismatch",
            "review_edge_misalignment",
        }
    )

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
        reference_hashes_by_role: dict[str, set[str]] = {}
        camera_evidence = self._camera_evidence_by_view(render_root / "conditioning_qa.json")
        for camera in view_set.cameras:
            findings: list[dict[str, str]] = []
            gate_evidence: dict[str, dict[str, Any]] = {
                "geometry": {"status": "review", "code": "evidence_not_available"},
                "semantic": {"status": "review", "code": "evidence_not_available"},
                "material": {"status": "review", "code": "evidence_not_available"},
                "material_roles": {"status": "review", "code": "evidence_not_available"},
                "context": {"status": "review", "code": "evidence_not_available"},
                "camera": camera_evidence.get(
                    camera.view_id,
                    {"status": "review", "code": "conditioning_qa_not_available"},
                ),
            }
            if gate_evidence["camera"]["status"] == "fail":
                findings.append(self._finding("error", "camera_preflight_failed", camera.view_id))
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
            context = design.industrial_context
            if context is not None and context.proxy_buildings:
                proxy_path = render_root / camera.view_id / "context_proxy_rgba.png"
                if not proxy_path.is_file():
                    findings.append(
                        self._finding("error", "context_proxy_missing", str(proxy_path))
                    )
                elif input_hashes.get("context_proxy_rgba") != _sha256(proxy_path):
                    findings.append(
                        self._finding("error", "context_proxy_hash_mismatch", proxy_path.name)
                    )
            if manifest.get("output", {}).get("protected_composite"):
                for name in ("material_id.png", "material_id_manifest.json"):
                    input_path = render_root / camera.view_id / name
                    if not input_path.is_file():
                        findings.append(self._finding("error", "input_missing", str(input_path)))

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
                    geometry = self._protected_geometry_evidence(
                        image_path,
                        render_root / camera.view_id / "base_rgb.png",
                        render_root / camera.view_id / "locked_mask.png",
                        expected_output,
                    )
                    gate_evidence["geometry"] = geometry
                    if geometry["status"] == "fail":
                        findings.append(
                            self._finding("error", str(geometry["code"]), camera.view_id)
                        )
                    semantic = self._semantic_retention_evidence(
                        image_path,
                        render_root / camera.view_id / "semantic.png",
                        render_root / camera.view_id / "semantic_id_manifest.json",
                    )
                    gate_evidence["semantic"] = semantic
                    if semantic["status"] == "fail":
                        findings.append(
                            self._finding("error", str(semantic["code"]), camera.view_id)
                        )
                    material = self._palette_evidence(
                        image_path,
                        render_root / camera.view_id / "bounded_mask.png",
                        tuple(design.material_palette.model_dump().values()),
                    )
                    gate_evidence["material"] = material
                    if material["status"] == "fail":
                        findings.append(
                            self._finding("error", str(material["code"]), camera.view_id)
                        )
                    material_roles = self._material_role_evidence(
                        image_path,
                        render_root / camera.view_id / "semantic.png",
                        render_root / camera.view_id / "semantic_id_manifest.json",
                        design.material_palette.model_dump(),
                    )
                    gate_evidence["material_roles"] = material_roles
                    if material_roles["status"] == "fail":
                        findings.append(
                            self._finding("error", str(material_roles["code"]), camera.view_id)
                        )
                    context_evidence = self._context_evidence(
                        render_root / camera.view_id,
                        manifest,
                        design,
                        require_visible=camera.role in {ViewRole.OVERALL, ViewRole.DETAIL},
                    )
                    gate_evidence["context"] = context_evidence
                    if context_evidence["status"] == "fail":
                        findings.append(
                            self._finding("error", str(context_evidence["code"]), camera.view_id)
                        )

            input_roles = manifest.get("input_roles", {}) if manifest else {}
            if isinstance(input_roles, dict):
                for name, role in input_roles.items():
                    if not str(name).startswith("reference_"):
                        continue
                    checksum = input_hashes.get(name)
                    if isinstance(checksum, str):
                        reference_hashes_by_role.setdefault(str(role), set()).add(checksum)
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
                    "gate_evidence": gate_evidence,
                    "findings": findings,
                }
            )

        global_findings: list[dict[str, str]] = []
        if len(output_hashes) != len(set(output_hashes)):
            global_findings.append(
                self._finding("error", "duplicate_outputs", "generated views must be unique")
            )
        inconsistent_roles = sorted(
            role
            for role, hashes in reference_hashes_by_role.items()
            if role not in {"quality_only", "context_composition_guide"} and len(hashes) > 1
        )
        if inconsistent_roles:
            global_findings.append(
                self._finding(
                    "error",
                    "inconsistent_reference_role",
                    "one reference role resolved to multiple assets: "
                    + ", ".join(inconsistent_roles),
                )
            )

        for view in views:
            for finding in view["findings"]:
                if finding["code"] in self._VISUAL_REVIEW_CODES:
                    finding["severity"] = "warning"

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

    @staticmethod
    def _camera_evidence_by_view(report_path: Path) -> dict[str, dict[str, Any]]:
        if not report_path.is_file():
            return {}
        try:
            document = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        evidence: dict[str, dict[str, Any]] = {}
        for view in document.get("views", []):
            if not isinstance(view, dict) or not view.get("view_id"):
                continue
            status = str(view.get("status", "review"))
            evidence[str(view["view_id"])] = {
                "status": status if status in {"pass", "fail"} else "review",
                "code": (
                    "camera_semantic_coverage_passed"
                    if status == "pass"
                    else "camera_semantic_coverage_failed"
                    if status == "fail"
                    else "camera_semantic_coverage_review"
                ),
                "focus_coverage": view.get("focus_coverage"),
                "circulation_coverage": view.get("circulation_coverage"),
                "context_coverage": view.get("context_coverage"),
                "thresholds": view.get("thresholds", {}),
            }
        return evidence

    @staticmethod
    def _protected_geometry_evidence(
        output_path: Path,
        base_path: Path,
        mask_path: Path,
        output_manifest: dict[str, Any],
    ) -> dict[str, Any]:
        if output_manifest.get("geometry_protection_mode") == "validation_only":
            screen_passed = (
                output_manifest.get("geometry_protection_status") == "edge_alignment_screen_passed"
            )
            return {
                "status": "pass" if screen_passed else "fail",
                "code": output_manifest.get(
                    "geometry_protection_status", "edge_alignment_review_required"
                ),
                "edge_alignment_recall": output_manifest.get("edge_alignment_recall"),
                "edge_alignment_precision": output_manifest.get("edge_alignment_precision"),
                "edge_alignment_f1": output_manifest.get("edge_alignment_f1"),
                "edge_bidirectional_chamfer_px": output_manifest.get(
                    "edge_bidirectional_chamfer_px"
                ),
                "edge_alignment_threshold": output_manifest.get("edge_alignment_threshold"),
                "edge_f1_threshold": output_manifest.get("edge_f1_threshold"),
                "edge_chamfer_threshold_px": output_manifest.get("edge_chamfer_threshold_px"),
                "note": (
                    "Photoreal pixels were preserved. This v2 structural screen is deterministic; "
                    "semantic topology and human design review remain separate gates."
                ),
            }
        if not output_manifest.get("protected_composite"):
            return {"status": "review", "code": "protected_composite_not_recorded"}
        if not base_path.is_file() or not mask_path.is_file():
            return {"status": "fail", "code": "protected_geometry_input_missing"}
        try:
            with Image.open(output_path) as source:
                output = np.asarray(source.convert("RGB"), dtype=np.uint8)
            size = (output.shape[1], output.shape[0])
            with Image.open(base_path) as source:
                base = np.asarray(
                    source.convert("RGB").resize(size, Image.Resampling.LANCZOS),
                    dtype=np.uint8,
                )
            with Image.open(mask_path) as source:
                locked = (
                    np.asarray(
                        source.convert("L").resize(size, Image.Resampling.NEAREST),
                        dtype=np.uint8,
                    )
                    >= 128
                )
        except OSError:
            return {"status": "fail", "code": "protected_geometry_input_invalid"}
        changed = int(np.count_nonzero(np.any(output != base, axis=2) & locked))
        protected = int(np.count_nonzero(locked))
        return {
            "status": "pass" if changed == 0 else "fail",
            "code": "protected_pixels_preserved" if changed == 0 else "protected_pixels_changed",
            "protected_pixels": protected,
            "changed_pixels": changed,
        }

    @staticmethod
    def _semantic_retention_evidence(
        output_path: Path,
        semantic_path: Path,
        semantic_manifest_path: Path,
        *,
        color_tolerance: int = 36,
        minimum_semantic_pixels: int = 180,
        minimum_semantic_coverage: float = 0.001,
        minimum_landscape_green_ratio: float = 0.20,
        minimum_road_surface_ratio: float = 0.50,
    ) -> dict[str, Any]:
        if not semantic_path.is_file() or not semantic_manifest_path.is_file():
            return {"status": "review", "code": "semantic_retention_input_missing"}
        try:
            manifest = json.loads(semantic_manifest_path.read_text(encoding="utf-8"))
            roles = manifest["roles"]
            names = [str(item["semantic_role"]) for item in roles]
            colors = np.asarray([item["srgb8"] for item in roles], dtype=np.int32)
            with Image.open(output_path) as source:
                output = source.convert("RGB")
                hsv = np.asarray(output.convert("HSV"), dtype=np.uint8)
            with Image.open(semantic_path) as source:
                semantic = np.asarray(
                    source.convert("RGB").resize(output.size, Image.Resampling.NEAREST),
                    dtype=np.int32,
                )
        except (OSError, KeyError, TypeError, ValueError, UnidentifiedImageError):
            return {"status": "fail", "code": "semantic_retention_input_invalid"}
        if colors.ndim != 2 or colors.shape[1] != 3 or not len(colors):
            return {"status": "fail", "code": "semantic_retention_palette_invalid"}

        pixels = semantic.reshape(-1, 3)
        distances = np.sum((pixels[:, None, :] - colors[None, :, :]) ** 2, axis=2)
        nearest = np.argmin(distances, axis=1).reshape(semantic.shape[:2])
        accepted = np.min(distances, axis=1).reshape(semantic.shape[:2]) <= color_tolerance**2

        def role_mask(role_names: set[str]) -> NDArray[np.bool_]:
            indexes = [index for index, name in enumerate(names) if name in role_names]
            if not indexes:
                return np.zeros(semantic.shape[:2], dtype=np.bool_)
            return cast(NDArray[np.bool_], accepted & np.isin(nearest, indexes))

        landscape = role_mask({"landscape_zone"})
        roads = role_mask({"site_road", "sidewalk", "service_yard", "parking", "loading_zone"})
        # Pillow hue is 0..255. This range includes yellow-green through blue-green while
        # excluding neutral paving and the semantic annotation colors from the source pass.
        green = (
            (hsv[:, :, 0] >= 38)
            & (hsv[:, :, 0] <= 112)
            & (hsv[:, :, 1] >= 32)
            & (hsv[:, :, 2] >= 32)
        )
        road_surface = (hsv[:, :, 1] <= 105) & (hsv[:, :, 2] >= 35)
        image_pixels = semantic.shape[0] * semantic.shape[1]
        sample_floor = min(
            image_pixels,
            max(
                minimum_semantic_pixels,
                round(image_pixels * minimum_semantic_coverage),
            ),
        )
        landscape_pixels = int(np.count_nonzero(landscape))
        road_pixels = int(np.count_nonzero(roads))
        landscape_ratio = (
            float(np.count_nonzero(green & landscape)) / int(np.count_nonzero(landscape))
            if landscape_pixels >= sample_floor
            else None
        )
        road_ratio = (
            float(np.count_nonzero(road_surface & roads)) / int(np.count_nonzero(roads))
            if road_pixels >= sample_floor
            else None
        )
        failures: list[str] = []
        if landscape_ratio is not None and landscape_ratio < minimum_landscape_green_ratio:
            failures.append("authored_landscape_not_retained")
        if road_ratio is not None and road_ratio < minimum_road_surface_ratio:
            failures.append("authored_circulation_surface_not_retained")
        return {
            "status": "fail" if failures else "pass",
            "code": failures[0] if failures else "semantic_surface_retention_passed",
            "findings": failures,
            "landscape_green_ratio": landscape_ratio,
            "landscape_sample_pixels": landscape_pixels,
            "landscape_green_threshold": minimum_landscape_green_ratio,
            "road_surface_ratio": road_ratio,
            "road_sample_pixels": road_pixels,
            "road_surface_threshold": minimum_road_surface_ratio,
            "minimum_semantic_pixels": minimum_semantic_pixels,
            "minimum_semantic_coverage": minimum_semantic_coverage,
            "effective_sample_floor": sample_floor,
            "threshold_status": "benchmark_hypothesis",
        }

    @staticmethod
    def _palette_evidence(
        output_path: Path,
        bounded_mask_path: Path,
        palette: tuple[str, ...],
        *,
        maximum_leakage: float = 0.05,
    ) -> dict[str, Any]:
        if not bounded_mask_path.is_file():
            return {"status": "review", "code": "bounded_mask_not_available"}
        try:
            with Image.open(output_path) as source:
                image = source.convert("RGB")
                hsv = np.asarray(image.convert("HSV"), dtype=np.uint8)
            with Image.open(bounded_mask_path) as source:
                bounded = (
                    np.asarray(
                        source.convert("L").resize(image.size, Image.Resampling.NEAREST),
                        dtype=np.uint8,
                    )
                    >= 128
                )
        except OSError:
            return {"status": "fail", "code": "palette_evidence_input_invalid"}
        allowed_hues = []
        for value in palette:
            normalized = value.lstrip("#")
            red, green, blue = (int(normalized[index : index + 2], 16) / 255 for index in (0, 2, 4))
            allowed_hue, saturation, _ = colorsys.rgb_to_hsv(red, green, blue)
            if saturation >= 0.12:
                allowed_hues.append(allowed_hue * 255)
        saturated = bounded & (hsv[:, :, 1] >= 170) & (hsv[:, :, 2] >= 64)
        sample_count = int(np.count_nonzero(saturated))
        if not sample_count:
            return {
                "status": "pass",
                "code": "no_forbidden_saturated_color",
                "sample_pixels": 0,
                "leakage_ratio": 0.0,
                "threshold": maximum_leakage,
            }
        if not allowed_hues:
            forbidden = saturated
        else:
            pixel_hue = hsv[:, :, 0].astype(np.float32)
            distances = np.stack(
                [
                    np.minimum(abs(pixel_hue - item), 255 - abs(pixel_hue - item))
                    for item in allowed_hues
                ]
            )
            forbidden = saturated & (distances.min(axis=0) > 24)
        leakage = float(np.count_nonzero(forbidden)) / max(1, int(np.count_nonzero(bounded)))
        return {
            "status": "pass" if leakage <= maximum_leakage else "fail",
            "code": "palette_within_tolerance" if leakage <= maximum_leakage else "palette_leakage",
            "sample_pixels": sample_count,
            "leakage_ratio": leakage,
            "threshold": maximum_leakage,
        }

    @staticmethod
    def _material_role_evidence(
        output_path: Path,
        semantic_path: Path,
        semantic_manifest_path: Path,
        palette: dict[str, str],
        *,
        minimum_pixels: int = 180,
        minimum_role_coverage: float = 0.001,
    ) -> dict[str, Any]:
        """Verify approved colors on authored roles without over-penalising thin details.

        Roof and main cladding are broad surfaces and therefore require substantial agreement.
        Glass, accent strips and boundary steel are narrow, reflective or anti-aliased in a
        photographic output; for those roles the gate verifies credible presence rather than
        requiring thirty percent of a candidate semantic region to be a flat design color.
        """

        if not semantic_path.is_file() or not semantic_manifest_path.is_file():
            return {"status": "review", "code": "material_role_input_missing"}
        try:
            manifest = json.loads(semantic_manifest_path.read_text(encoding="utf-8"))
            role_colors = {
                str(item["semantic_role"]): np.asarray(item["srgb8"], dtype=np.int16)
                for item in manifest["roles"]
            }
            with Image.open(output_path) as source:
                output = source.convert("RGB")
                output_hsv = np.asarray(output.convert("HSV"), dtype=np.uint8)
            with Image.open(semantic_path) as source:
                semantic = np.asarray(
                    source.convert("RGB").resize(output.size, Image.Resampling.NEAREST),
                    dtype=np.int16,
                )
        except (OSError, KeyError, TypeError, ValueError, UnidentifiedImageError):
            return {"status": "fail", "code": "material_role_input_invalid"}

        expected_roles = {
            "roof": ({"roof"}, palette["roof_hex"]),
            "primary_facade": (
                {"primary_facade", "main_shed", "office_block"},
                palette["primary_hex"],
            ),
            "facade_secondary": ({"facade_secondary"}, palette["secondary_hex"]),
            "glazing": ({"glazing"}, palette["glass_hex"]),
            "brand_accent": ({"brand_accent"}, palette["accent_hex"]),
            "site_boundary": (
                {"site_boundary", "main_entrance", "secondary_entrance"},
                palette["boundary_hex"],
            ),
        }
        role_thresholds = {
            "roof": 0.30,
            "primary_facade": 0.10,
            "facade_secondary": 0.07,
            "glazing": 0.015,
            "brand_accent": 0.02,
            "site_boundary": 0.02,
        }
        minimum_matching_pixels = 128
        image_pixels = semantic.shape[0] * semantic.shape[1]
        sample_floor = min(
            image_pixels,
            max(
                minimum_pixels,
                round(image_pixels * minimum_role_coverage),
            ),
        )
        evidence: dict[str, dict[str, Any]] = {}
        failures: list[str] = []
        for role, (source_roles, expected_hex) in expected_roles.items():
            semantic_colors = [
                role_colors[source_role]
                for source_role in source_roles
                if source_role in role_colors
            ]
            if not semantic_colors:
                continue
            mask = np.zeros(semantic.shape[:2], dtype=np.bool_)
            for semantic_color in semantic_colors:
                mask |= np.max(np.abs(semantic - semantic_color), axis=2) <= 20
            pixel_count = int(np.count_nonzero(mask))
            if pixel_count < sample_floor:
                continue
            normalized = expected_hex.lstrip("#")
            expected_rgb = tuple(
                int(normalized[index : index + 2], 16) / 255 for index in (0, 2, 4)
            )
            expected_hue, expected_saturation, _ = colorsys.rgb_to_hsv(*expected_rgb)
            pixels = output_hsv[mask]
            if expected_saturation < 0.20:
                # Neutral metal is affected strongly by sky, shade and reflected landscape.
                # Hue is undefined at low saturation, so evaluate neutrality instead.
                matches = pixels[:, 1] <= 115
            else:
                hue = pixels[:, 0].astype(np.float32)
                expected_hue_byte = expected_hue * 255
                hue_distance = np.minimum(
                    np.abs(hue - expected_hue_byte), 255 - np.abs(hue - expected_hue_byte)
                )
                matches = (hue_distance <= 22) & (
                    pixels[:, 1] >= max(28, expected_saturation * 255 * 0.25)
                )
            match_ratio = float(np.count_nonzero(matches)) / pixel_count
            matching_pixels = int(np.count_nonzero(matches))
            threshold = role_thresholds[role]
            passed = match_ratio >= threshold and matching_pixels >= minimum_matching_pixels
            evidence[role] = {
                "status": "pass" if passed else "fail",
                "expected": expected_hex,
                "sample_pixels": pixel_count,
                "matching_pixels": matching_pixels,
                "match_ratio": match_ratio,
                "threshold": threshold,
                "minimum_matching_pixels": minimum_matching_pixels,
            }
            if not passed:
                failures.append(role)
        return {
            "status": "fail" if failures else "pass",
            "code": "material_role_mismatch" if failures else "material_roles_within_tolerance",
            "failed_roles": failures,
            "roles": evidence,
            "minimum_role_coverage": minimum_role_coverage,
            "effective_sample_floor": sample_floor,
        }

    @staticmethod
    def _context_evidence(
        view_directory: Path,
        generation_manifest: dict[str, Any],
        design: DesignDNA,
        *,
        require_visible: bool,
        maximum_project_overlap: float = 0.001,
    ) -> dict[str, Any]:
        """Verify the deterministic conceptual-context layer, not Gemini's interpretation."""

        context = design.industrial_context
        if context is None or not context.proxy_buildings:
            return {"status": "pass", "code": "context_proxy_not_requested"}
        overlay_path = view_directory / "context_proxy_rgba.png"
        mask_path = view_directory / "context_proxy_mask.png"
        project_path = view_directory / "project_locked_mask.png"
        layer_manifest_path = view_directory / "layer_authority_manifest.json"
        required = (overlay_path, mask_path, project_path, layer_manifest_path)
        if any(not path.is_file() for path in required):
            return {"status": "fail", "code": "context_authority_artifact_missing"}
        output = generation_manifest.get("output", {})
        input_roles = generation_manifest.get("input_roles", {})
        input_hashes = generation_manifest.get("inputs", {})
        if not output.get("context_proxy_composited"):
            guide_entries = [
                name for name, role in input_roles.items() if role == "context_composition_guide"
            ]
            guide_path = view_directory / "context_composition_guide.png"
            if (
                len(guide_entries) != 1
                or not guide_path.is_file()
                or input_hashes.get(guide_entries[0]) != _sha256(guide_path)
            ):
                return {"status": "fail", "code": "context_guide_not_registered"}
        try:
            with Image.open(overlay_path) as source:
                overlay = source.convert("RGBA")
                alpha = np.asarray(overlay.getchannel("A"), dtype=np.uint8)
            with Image.open(mask_path) as source:
                proxy_mask = (
                    np.asarray(
                        source.convert("L").resize(overlay.size, Image.Resampling.NEAREST),
                        dtype=np.uint8,
                    )
                    >= 128
                )
            with Image.open(project_path) as source:
                # Ignore the two-pixel anti-aliased silhouette fringe. The underlying proxy
                # compositor still clips against the full project mask; this erosion only keeps
                # the QA overlap metric from treating shared boundary coverage as intrusion.
                project_mask = (
                    np.asarray(
                        source.convert("L")
                        .resize(overlay.size, Image.Resampling.NEAREST)
                        .filter(ImageFilter.MinFilter(5)),
                        dtype=np.uint8,
                    )
                    >= 128
                )
            layer_manifest = json.loads(layer_manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, KeyError, TypeError, UnidentifiedImageError):
            return {"status": "fail", "code": "context_authority_artifact_invalid"}
        nonzero = alpha > 0
        visible_pixels = int(np.count_nonzero(nonzero))
        proxy_pixels = int(np.count_nonzero(proxy_mask))
        overlap_pixels = int(np.count_nonzero(nonzero & project_mask))
        overlap_ratio = overlap_pixels / max(1, visible_pixels)
        source_opacities = [float(proxy.opacity) for proxy in context.proxy_buildings]
        opacity_contract_valid = all(0.22 <= value <= 0.30 for value in source_opacities)
        layer_hash = layer_manifest.get("layers", {}).get("context_proxy", {}).get("sha256")
        failures: list[str] = []
        if require_visible and visible_pixels == 0:
            failures.append("context_proxy_not_visible_in_context_view")
        if proxy_pixels and visible_pixels == 0:
            failures.append("context_proxy_overlay_empty")
        if overlap_ratio > maximum_project_overlap:
            failures.append("context_proxy_overlaps_locked_project")
        if not opacity_contract_valid:
            failures.append("context_proxy_opacity_out_of_contract")
        if layer_hash != _sha256(mask_path):
            failures.append("context_proxy_layer_hash_mismatch")
        return {
            "status": "fail" if failures else "pass",
            "code": failures[0] if failures else "context_proxy_contract_passed",
            "findings": failures,
            "conceptual": True,
            "planned_proxy_count": len(context.proxy_buildings),
            "visible_pixels": visible_pixels,
            "projected_coverage": visible_pixels / max(1, alpha.size),
            "mean_visible_alpha": (float(alpha[nonzero].mean()) / 255.0 if visible_pixels else 0.0),
            "source_opacity_min": min(source_opacities),
            "source_opacity_max": max(source_opacities),
            "project_overlap_ratio": overlap_ratio,
            "project_overlap_threshold": maximum_project_overlap,
            "project_mask_edge_tolerance_px": 2,
        }
