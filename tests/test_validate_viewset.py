import hashlib
import json
from pathlib import Path

from PIL import Image

from v365_archviz.application.validate_viewset import ValidateGeneratedViewSet
from v365_archviz.domain.design import DesignDNA, DesignLanguage, EnvironmentDesign
from v365_archviz.domain.workflow import Camera, ViewRole, ViewSet


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _contracts(root: Path) -> tuple[Path, Path]:
    design = DesignDNA(
        project_id="project",
        design_revision="R01-test",
        design_language=DesignLanguage(
            style="style",
            primary_material="primary",
            secondary_material="secondary",
            office_material="office",
        ),
        environment=EnvironmentDesign(
            time="09:00",
            weather="clear",
            sun_azimuth_deg=120,
            sun_elevation_deg=45,
            white_balance_k=5600,
        ),
        buildings=(),
        grammar_version="test",
        asset_library_version="test",
    )
    view_set = ViewSet(
        view_set_id="views",
        design_revision=design.design_revision,
        cameras=(
            Camera(
                view_id="view-01",
                role=ViewRole.OVERALL,
                position=(1, 1, 1),
                target=(0, 0, 0),
                focal_length_mm=35,
                sensor_width_mm=36,
                aspect_ratio="16:9",
            ),
        ),
    )
    design_path = root / "design.json"
    view_set_path = root / "views.json"
    design_path.write_text(design.model_dump_json(), encoding="utf-8")
    view_set_path.write_text(view_set.model_dump_json(), encoding="utf-8")
    return view_set_path, design_path


def test_validates_complete_generated_view_set(tmp_path: Path) -> None:
    render_view = tmp_path / "renders" / "view-01"
    generated_view = tmp_path / "generated" / "view-01"
    render_view.mkdir(parents=True)
    generated_view.mkdir(parents=True)
    inputs: dict[str, str] = {}
    for name in ("base_rgb", "depth", "instance_id", "semantic", "edges"):
        path = render_view / f"{name}.png"
        Image.new("RGB", (16, 9), "white").save(path)
        inputs[name] = _hash(path)
    output = generated_view / "refined.jpg"
    Image.new("RGB", (1024, 576), "green").save(output)
    (generated_view / "generation_manifest.json").write_text(
        json.dumps(
            {
                "view_id": "view-01",
                "project_id": "project",
                "design_revision": "R01-test",
                "inputs": inputs,
                "output": {"sha256": _hash(output), "media_type": "image/jpeg"},
            }
        ),
        encoding="utf-8",
    )
    view_set_path, design_path = _contracts(tmp_path)

    result = ValidateGeneratedViewSet().execute(
        tmp_path / "renders",
        tmp_path / "generated",
        view_set_path,
        design_path,
    )

    assert result.passed
    report = json.loads(result.report_path.read_text(encoding="utf-8"))
    finder = report["views"][0]
    assert finder["technical_status"] == "pass"
    assert report["human_review_required"] is True


def test_detects_stale_conditioning_input(tmp_path: Path) -> None:
    render_view = tmp_path / "renders" / "view-01"
    generated_view = tmp_path / "generated" / "view-01"
    render_view.mkdir(parents=True)
    generated_view.mkdir(parents=True)
    inputs: dict[str, str] = {}
    for name in ("base_rgb", "depth", "instance_id", "semantic", "edges"):
        path = render_view / f"{name}.png"
        Image.new("RGB", (16, 9), "white").save(path)
        inputs[name] = _hash(path)
    output = generated_view / "refined.jpg"
    Image.new("RGB", (1024, 576), "green").save(output)
    (generated_view / "generation_manifest.json").write_text(
        json.dumps(
            {
                "view_id": "view-01",
                "project_id": "project",
                "design_revision": "R01-test",
                "inputs": {**inputs, "edges": "stale"},
                "output": {"sha256": _hash(output), "media_type": "image/jpeg"},
            }
        ),
        encoding="utf-8",
    )
    view_set_path, design_path = _contracts(tmp_path)

    result = ValidateGeneratedViewSet().execute(
        tmp_path / "renders",
        tmp_path / "generated",
        view_set_path,
        design_path,
    )

    assert not result.passed
    report = json.loads(result.report_path.read_text(encoding="utf-8"))
    codes = {finding["code"] for finding in report["views"][0]["findings"]}
    assert "input_hash_mismatch" in codes
