import hashlib
import io
import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image
from pydantic import ValidationError

from v365_archviz.application.build_control_pack import BuildControlPack
from v365_archviz.application.compose_viewset_board import ComposeViewSetBoard
from v365_archviz.application.create_certification_report import CreateCertificationReport
from v365_archviz.application.protect_refinement import ProtectRefinement
from v365_archviz.application.validate_conditioning import ValidateConditioningViewSet
from v365_archviz.application.validate_viewset import ValidateGeneratedViewSet
from v365_archviz.domain.controlled_realism import (
    AssetLibraryManifest,
    CertificationEvidence,
    CertificationReport,
    CertificationState,
)
from v365_archviz.domain.qa import QAGate, QAStatus


def _save_rgb(path: Path, color: tuple[int, int, int], size: tuple[int, int] = (8, 6)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path)


def _png_bytes(color: tuple[int, int, int], size: tuple[int, int] = (8, 6)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, format="PNG")
    return buffer.getvalue()


def test_control_pack_is_a_complete_partition_and_promotes_edges(tmp_path: Path) -> None:
    view = tmp_path / "view-01"
    view.mkdir()
    policy = np.zeros((6, 8, 3), dtype=np.uint8)
    policy[:, :2, 0] = 255
    policy[:, 2:6, 1] = 255
    policy[:, 6:, 2] = 255
    Image.fromarray(policy, mode="RGB").save(view / "control_policy.png")
    edges = np.zeros((6, 8), dtype=np.uint8)
    edges[3, 4] = 255
    Image.fromarray(edges, mode="L").save(view / "edges.png")
    base = np.full((6, 8, 3), (86, 178, 94), dtype=np.uint8)
    base[:, :2] = (190, 195, 198)
    Image.fromarray(base, mode="RGB").save(view / "base_rgb.png")

    manifest = BuildControlPack().execute(view, edge_band_px=3)

    masks = [np.asarray(Image.open(item.path).convert("1"), dtype=bool) for item in manifest.masks]
    assert np.all(np.stack(masks).sum(axis=0) == 1)
    assert manifest.overlap_pixels == 0
    assert manifest.uncovered_pixels == 0
    assert Path(manifest.structure_guide_ref).is_file()
    assert hashlib.sha256(Path(manifest.structure_guide_ref).read_bytes()).hexdigest() == (
        manifest.structure_guide_sha256
    )
    with Image.open(manifest.structure_guide_ref) as guide:
        guide_rgb = np.asarray(guide.convert("RGB"), dtype=np.int16)
    assert np.max(np.abs(guide_rgb[:, :, 0] - guide_rgb[:, :, 1])) <= 8
    assert np.max(np.abs(guide_rgb[:, :, 1] - guide_rgb[:, :, 2])) <= 8
    locked = np.asarray(Image.open(view / "locked_mask.png").convert("L")) > 0
    assert locked[3, 4]
    assert locked[3, 3]


def test_checked_in_asset_library_is_valid_and_contains_pbr_foundation() -> None:
    manifest_path = Path("assets/pbr-v1/asset_library_manifest.json")
    library = AssetLibraryManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))

    assert library.library_version == "baseline-assets-v2"
    assert {role for asset in library.assets for role in asset.semantic_roles} >= {
        "roof",
        "main_shed",
        "site_road",
        "landscape_zone",
        "context_landscape",
    }
    assert {asset.kind.value for asset in library.assets} >= {"material", "environment"}
    assert any(asset.memory_class == "1K" for asset in library.assets)
    geometry_assets = [
        asset for asset in library.assets if asset.kind.value in {"vegetation", "vehicle", "person"}
    ]
    assert {asset.kind.value for asset in geometry_assets} == {
        "vegetation",
        "vehicle",
        "person",
    }
    assert all(asset.physical_dimensions_m is not None for asset in geometry_assets)
    for asset in library.assets:
        for item in asset.files:
            path = manifest_path.parent / item.path
            assert path.is_file()
            assert hashlib.sha256(path.read_bytes()).hexdigest() == item.sha256


def test_protected_compositor_restores_locked_base_pixels(tmp_path: Path) -> None:
    render = tmp_path / "renders" / "view-01"
    generated = tmp_path / "generated" / "view-01"
    _save_rgb(render / "base_rgb.png", (255, 0, 0), (4, 2))
    mask = Image.new("L", (4, 2), 0)
    mask.putpixel((0, 0), 255)
    mask.save(render / "locked_mask.png")
    Image.new("L", (4, 2), 0).save(render / "edges.png")
    (render / "control_pack_manifest.json").write_text("{}", encoding="utf-8")
    generated.mkdir(parents=True)
    (generated / "refined.jpg").write_bytes(_png_bytes((0, 0, 255), (4, 2)))
    (generated / "generation_manifest.json").write_text(
        json.dumps({"output": {"media_type": "image/jpeg", "sha256": "old"}}),
        encoding="utf-8",
    )

    result = ProtectRefinement().execute(tmp_path / "renders", tmp_path / "generated")

    with Image.open(generated / "refined.png") as image:
        assert image.getpixel((0, 0)) == (255, 0, 0)
        assert image.getpixel((3, 1)) == (0, 0, 255)
    assert not (generated / "refined.jpg").exists()
    assert (generated / "provider_source.jpg").is_file()
    document = json.loads((generated / "generation_manifest.json").read_text())
    assert document["output"]["protected_composite"] is True
    assert (
        document["output"]["sha256"]
        == hashlib.sha256((generated / "refined.png").read_bytes()).hexdigest()
    )
    assert result.view_count == 1
    assert result.promoted_count == 1

    geometry = ValidateGeneratedViewSet._protected_geometry_evidence(
        generated / "refined.png",
        render / "base_rgb.png",
        render / "locked_mask.png",
        document["output"],
    )
    assert geometry["status"] == "pass"
    assert geometry["changed_pixels"] == 0


def test_validation_only_protection_keeps_photoreal_provider_pixels(tmp_path: Path) -> None:
    render = tmp_path / "renders" / "view-01"
    generated = tmp_path / "generated" / "view-01"
    _save_rgb(render / "base_rgb.png", (255, 0, 0), (4, 2))
    Image.new("L", (4, 2), 255).save(render / "locked_mask.png")
    Image.new("L", (4, 2), 0).save(render / "edges.png")
    (render / "control_pack_manifest.json").write_text("{}", encoding="utf-8")
    generated.mkdir(parents=True)
    (generated / "refined.png").write_bytes(_png_bytes((0, 0, 255), (4, 2)))
    (generated / "generation_manifest.json").write_text(
        json.dumps({"output": {"media_type": "image/png", "sha256": "old"}}),
        encoding="utf-8",
    )

    result = ProtectRefinement().execute(
        tmp_path / "renders",
        tmp_path / "generated",
        restore_locked_pixels=False,
    )

    with Image.open(generated / "refined.png") as image:
        assert image.getpixel((0, 0)) == (0, 0, 255)
    document = json.loads((generated / "generation_manifest.json").read_text())
    assert document["output"]["protected_composite"] is False
    assert document["output"]["geometry_protection_mode"] == "validation_only"
    # This fixture has no authoritative edge under LOCKED, so the structural screen measured
    # nothing. Validation-only ships the provider pixels unchanged, so an unmeasurable screen
    # must be reported as unverifiable instead of being promoted on an invented perfect score.
    assert document["output"]["geometry_protection_status"] == "edge_alignment_unverifiable"
    assert document["output"]["edge_alignment_verifiable"] is False
    assert result.promoted_count == 0
    assert result.rejected_count == 1


def test_validation_only_screen_promotes_when_locked_edges_align(tmp_path: Path) -> None:
    """A measurable, aligned screen still promotes in validation-only mode."""

    size = (48, 48)
    render = tmp_path / "renders" / "view-01"
    generated = tmp_path / "generated" / "view-01"
    base = Image.new("RGB", size, (255, 255, 255))
    edges = Image.new("L", size, 0)
    refined = Image.new("RGB", size, (255, 255, 255))
    for y in range(size[1]):
        # A detected edge occupies the transition band either side of the drawn line, so the
        # authoritative band is written at the same width the screen will measure.
        for x in (23, 24, 25):
            edges.putpixel((x, y), 255)
        refined.putpixel((24, y), (0, 0, 0))
    render.mkdir(parents=True)
    base.save(render / "base_rgb.png")
    edges.save(render / "edges.png")
    Image.new("L", size, 255).save(render / "locked_mask.png")
    (render / "control_pack_manifest.json").write_text("{}", encoding="utf-8")
    generated.mkdir(parents=True)
    refined.save(generated / "refined.png")
    (generated / "generation_manifest.json").write_text(
        json.dumps({"output": {"media_type": "image/png", "sha256": "old"}}),
        encoding="utf-8",
    )

    result = ProtectRefinement().execute(
        tmp_path / "renders",
        tmp_path / "generated",
        restore_locked_pixels=False,
    )

    document = json.loads((generated / "generation_manifest.json").read_text())
    assert document["output"]["edge_alignment_verifiable"] is True
    assert document["output"]["geometry_protection_status"] == "edge_alignment_screen_passed"
    assert result.promoted_count == 1


def test_validation_only_can_composite_registered_context_after_generation(tmp_path: Path) -> None:
    render = tmp_path / "renders" / "view-01"
    generated = tmp_path / "generated" / "view-01"
    _save_rgb(render / "base_rgb.png", (255, 255, 255), (4, 2))
    Image.new("L", (4, 2), 255).save(render / "locked_mask.png")
    Image.new("L", (4, 2), 0).save(render / "edges.png")
    Image.new("RGBA", (4, 2), (190, 190, 190, 96)).save(render / "context_proxy_rgba.png")
    (render / "control_pack_manifest.json").write_text("{}", encoding="utf-8")
    generated.mkdir(parents=True)
    (generated / "refined.png").write_bytes(_png_bytes((20, 40, 60), (4, 2)))
    (generated / "generation_manifest.json").write_text(
        json.dumps({"output": {"media_type": "image/png", "sha256": "old"}}),
        encoding="utf-8",
    )

    ProtectRefinement().execute(
        tmp_path / "renders",
        tmp_path / "generated",
        restore_locked_pixels=False,
        composite_context_proxy=True,
    )

    with Image.open(generated / "refined.png") as image:
        assert image.convert("RGB").getpixel((0, 0)) != (20, 40, 60)
    document = json.loads((generated / "generation_manifest.json").read_text())
    assert document["output"]["context_proxy_composited"] is True
    assert (
        document["output"]["context_proxy_sha256"]
        == hashlib.sha256((render / "context_proxy_rgba.png").read_bytes()).hexdigest()
    )


def test_geometry_v2_penalizes_invented_locked_edges(tmp_path: Path) -> None:
    size = (12, 8)
    generated = Image.new("L", size, 0)
    for y in range(size[1]):
        generated.putpixel((3, y), 255)
        generated.putpixel((9, y), 255)
    authoritative = Image.new("L", size, 0)
    for y in range(size[1]):
        authoritative.putpixel((3, y), 255)
    edge_path = tmp_path / "edges.png"
    authoritative.save(edge_path)
    locked = Image.new("L", size, 255)

    metrics = ProtectRefinement._edge_geometry_metrics(generated.convert("RGB"), edge_path, locked)

    assert metrics.recall == 1.0
    assert metrics.precision < metrics.recall
    assert metrics.f1 < 1.0
    assert metrics.bidirectional_chamfer_px > 0


def test_palette_gate_rejects_large_unapproved_saturated_region(tmp_path: Path) -> None:
    output = tmp_path / "output.png"
    bounded = tmp_path / "bounded.png"
    _save_rgb(output, (150, 20, 220))
    Image.new("L", (8, 6), 255).save(bounded)

    evidence = ValidateGeneratedViewSet._palette_evidence(
        output,
        bounded,
        ("#E7E5DF", "#252B31", "#315263", "#2F6B4F", "#777B7A"),
    )

    assert evidence["status"] == "fail"
    assert evidence["code"] == "palette_leakage"


def test_semantic_gate_rejects_paving_over_authored_landscape(tmp_path: Path) -> None:
    output = tmp_path / "output.png"
    semantic = tmp_path / "semantic.png"
    manifest = tmp_path / "semantic_id_manifest.json"
    _save_rgb(output, (170, 170, 170))
    _save_rgb(semantic, (63, 231, 97))
    manifest.write_text(
        json.dumps({"roles": [{"semantic_role": "landscape_zone", "srgb8": [63, 231, 97]}]}),
        encoding="utf-8",
    )

    evidence = ValidateGeneratedViewSet._semantic_retention_evidence(output, semantic, manifest)

    assert evidence["status"] == "fail"
    assert evidence["code"] == "authored_landscape_not_retained"


def test_board_prefers_validated_refined_output_over_provider_source(tmp_path: Path) -> None:
    generated = tmp_path / "generated"
    view = generated / "view-01"
    view.mkdir(parents=True)
    _save_rgb(view / "refined.png", (255, 0, 0), (16, 9))
    _save_rgb(view / "provider_source.png", (0, 0, 255), (16, 9))

    board_path = generated / "board.jpg"
    ComposeViewSetBoard().execute(
        generated,
        board_path,
        columns=1,
        cell_width=16,
        cell_height=9,
    )

    with Image.open(board_path) as board:
        red, _, blue = board.convert("RGB").getpixel((8, 48))
    assert red > blue


def test_conditioning_camera_preflight_measures_semantic_coverage(tmp_path: Path) -> None:
    scene = {
        "source": {
            "provider": "local_fixture",
            "project_id": "project",
            "model_id": "model",
            "version_id": "version",
        },
        "coordinate_system": {
            "source_to_world": [
                [1, 0, 0, 0],
                [0, 1, 0, 0],
                [0, 0, 1, 0],
                [0, 0, 0, 1],
            ]
        },
        "elements": [
            {
                "scene_element_id": "shed",
                "source": {"external_id": "shed"},
                "transform": [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]],
                "mesh_ref": "shed.npz",
                "bounding_box": {"minimum": [0, 0, 0], "maximum": [10, 10, 5]},
                "semantic_role": "main_shed",
            },
            {
                "scene_element_id": "road",
                "source": {"external_id": "road"},
                "transform": [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]],
                "mesh_ref": "road.npz",
                "bounding_box": {"minimum": [0, -2, 0], "maximum": [10, 0, 0.1]},
                "semantic_role": "site_road",
            },
        ],
    }
    view_set = {
        "view_set_id": "views",
        "design_revision": "design",
        "cameras": [
            {
                "view_id": "view-01",
                "role": "overall",
                "position": [20, 20, 20],
                "target": [5, 5, 2],
                "focal_length_mm": 45,
                "sensor_width_mm": 36,
                "aspect_ratio": "16:9",
            }
        ],
    }
    scene_path = tmp_path / "scene.json"
    view_set_path = tmp_path / "view_set.json"
    scene_path.write_text(json.dumps(scene), encoding="utf-8")
    view_set_path.write_text(json.dumps(view_set), encoding="utf-8")
    view_root = tmp_path / "renders" / "view-01"
    view_root.mkdir(parents=True)
    # Bright sky exercises the int32 distance path; int16 squaring would overflow and
    # incorrectly count these pixels as a dark semantic class.
    pixels = np.full((10, 10, 3), 255, dtype=np.uint8)
    pixels[:3, :, :] = (238, 108, 89)
    pixels[3:5, :, :] = (118, 118, 118)
    Image.fromarray(pixels, mode="RGB").save(view_root / "semantic.png")
    (view_root / "semantic_id_manifest.json").write_text(
        json.dumps(
            {
                "roles": [
                    {"semantic_role": "main_shed", "srgb8": [238, 108, 89]},
                    {"semantic_role": "site_road", "srgb8": [118, 118, 118]},
                ]
            }
        ),
        encoding="utf-8",
    )

    result = ValidateConditioningViewSet().execute(scene_path, view_set_path, tmp_path / "renders")

    assert result.passed is True
    report = json.loads(result.report_path.read_text(encoding="utf-8"))
    assert report["views"][0]["focus_coverage"] == pytest.approx(0.3)
    assert report["views"][0]["circulation_coverage"] == pytest.approx(0.2)
    assert report["views"][0]["role_target_coverage"] == pytest.approx(0.2)
    assert report["views"][0]["available_role_targets"] == ["site_road"]


def test_conditioning_camera_preflight_measures_central_occluder_crop(
    tmp_path: Path,
) -> None:
    pixels = np.full((10, 10, 3), 255, dtype=np.uint8)
    pixels[2:8, 2:8, :] = (246, 234, 80)
    image_path = tmp_path / "semantic.png"
    manifest_path = tmp_path / "semantic_id_manifest.json"
    Image.fromarray(pixels, mode="RGB").save(image_path)
    manifest_path.write_text(
        json.dumps({"roles": [{"semantic_role": "vehicle", "srgb8": [246, 234, 80]}]}),
        encoding="utf-8",
    )

    coverage = ValidateConditioningViewSet._semantic_coverage(
        image_path,
        manifest_path,
        36,
        crop=(0.25, 0.20, 0.75, 0.80),
    )

    assert coverage["vehicle"] == pytest.approx(1.0)


def test_protected_compositor_does_not_promote_misaligned_candidate(tmp_path: Path) -> None:
    render = tmp_path / "renders" / "view-01"
    generated = tmp_path / "generated" / "view-01"
    _save_rgb(render / "base_rgb.png", (255, 255, 255), (12, 8))
    Image.new("L", (12, 8), 255).save(render / "locked_mask.png")
    edge = Image.new("L", (12, 8), 0)
    for y in range(8):
        edge.putpixel((5, y), 255)
    edge.save(render / "edges.png")
    (render / "control_pack_manifest.json").write_text("{}", encoding="utf-8")
    generated.mkdir(parents=True)
    (generated / "refined.jpg").write_bytes(_png_bytes((0, 0, 255), (12, 8)))
    (generated / "generation_manifest.json").write_text(
        json.dumps({"output": {"media_type": "image/png", "sha256": "old"}}),
        encoding="utf-8",
    )

    result = ProtectRefinement().execute(tmp_path / "renders", tmp_path / "generated")

    assert result.promoted_count == 0
    assert result.rejected_count == 1
    assert (generated / "refined.jpg").is_file()
    assert not (generated / "refined.png").exists()
    document = json.loads((generated / "generation_manifest.json").read_text())
    assert document["output"]["geometry_protection_status"] == "rejected_edge_misalignment"


def test_certification_fails_closed_without_hard_gate_evidence() -> None:
    with pytest.raises(ValidationError, match="passing evidence"):
        CertificationReport(
            report_id="cert-1",
            project_id="project",
            model_revision="model",
            design_revision="design",
            view_set_id="views",
            state=CertificationState.GEOMETRY_CERTIFIED,
            evidence=(
                CertificationEvidence(
                    gate=QAGate.ARTIFACT_INTEGRITY,
                    status=QAStatus.PASS,
                    evidence_refs=("technical_qa.json",),
                    message="passed",
                ),
            ),
        )


def test_approved_final_requires_realism_and_aesthetic_evidence() -> None:
    hard_gates = {
        QAGate.ARTIFACT_INTEGRITY,
        QAGate.GEOMETRY,
        QAGate.SEMANTIC,
        QAGate.MATERIAL,
        QAGate.CROSS_VIEW_APPEARANCE,
        QAGate.CAMERA,
    }
    evidence = tuple(
        CertificationEvidence(
            gate=gate,
            status=QAStatus.PASS,
            evidence_refs=(f"{gate.value}.json",),
            message="passed",
        )
        for gate in hard_gates
    )

    with pytest.raises(ValidationError, match="realism and aesthetic"):
        CertificationReport(
            report_id="cert-final",
            project_id="project",
            model_revision="model",
            design_revision="design",
            view_set_id="views",
            state=CertificationState.APPROVED_FINAL,
            evidence=evidence,
            reviewer="architect@example.com",
        )


def test_certification_labels_missing_visual_evidence_as_review(tmp_path: Path) -> None:
    consistency = {
        "report_id": "consistency-1",
        "project_id": "project",
        "model_revision": "model",
        "design_revision": "design",
        "view_set_id": "views",
        "status": "review",
        "findings": [
            {
                "finding_id": f"review-{gate.value}",
                "gate": gate.value,
                "status": "review",
                "code": "evidence_not_available",
                "message": "Review is required.",
                "view_ids": ["view-01"],
            }
            for gate in QAGate
            if gate is not QAGate.ARTIFACT_INTEGRITY
        ],
    }
    consistency_path = tmp_path / "consistency.json"
    technical_path = tmp_path / "technical.json"
    protected_path = tmp_path / "protected.json"
    consistency_path.write_text(json.dumps(consistency), encoding="utf-8")
    technical_path.write_text("{}", encoding="utf-8")
    protected_path.write_text("{}", encoding="utf-8")

    report = CreateCertificationReport().execute(
        consistency_path,
        technical_path,
        protected_path,
        tmp_path / "certification.json",
    )

    assert report.state is CertificationState.MARKETING_GENERATIVE_REVIEW
    integrity = next(item for item in report.evidence if item.gate is QAGate.ARTIFACT_INTEGRITY)
    assert integrity.status is QAStatus.PASS


def test_context_composite_reaches_the_unbranded_deliverable(tmp_path: Path) -> None:
    """Generation writes unbranded_refined first, and branding reuses it rather than the
    composited file, so the composite has to update it too or it never ships."""

    size = (16, 16)
    render = tmp_path / "renders" / "view-01"
    generated = tmp_path / "generated" / "view-01"
    render.mkdir(parents=True)
    generated.mkdir(parents=True)
    _save_rgb(render / "base_rgb.png", (255, 255, 255), size)
    Image.new("L", size, 0).save(render / "edges.png")
    Image.new("L", size, 255).save(render / "locked_mask.png")
    (render / "control_pack_manifest.json").write_text("{}", encoding="utf-8")
    overlay = Image.new("RGBA", size, (0, 0, 0, 0))
    for x in range(size[0]):
        for y in range(4):
            overlay.putpixel((x, y), (10, 20, 30, 255))
    overlay.save(render / "context_proxy_rgba.png")
    Image.new("RGB", size, (255, 255, 255)).save(generated / "refined.png")
    Image.new("RGB", size, (255, 255, 255)).save(generated / "unbranded_refined.png")
    (generated / "generation_manifest.json").write_text(
        json.dumps({"output": {"media_type": "image/png", "sha256": "old"}}), encoding="utf-8"
    )

    ProtectRefinement().execute(
        tmp_path / "renders",
        tmp_path / "generated",
        restore_locked_pixels=False,
        composite_context_proxy=True,
    )

    with Image.open(generated / "unbranded_refined.png") as unbranded:
        assert unbranded.getpixel((0, 0)) == (10, 20, 30)
    document = json.loads((generated / "generation_manifest.json").read_text())
    assert document["output"]["context_proxy_composited"] is True
