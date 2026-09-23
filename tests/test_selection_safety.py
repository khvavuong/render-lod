import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from v365_archviz.domain.workflow import Camera, ViewRole, ViewSet


def _load_script():
    path = Path(__file__).resolve().parents[1] / "scripts/select_best_views.py"
    spec = importlib.util.spec_from_file_location("quality_selection", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("audit_status", ["fail", "review", "unverified", "pass"])
def test_rejected_view_is_not_exported_as_a_fallback(tmp_path, monkeypatch, audit_status):
    module = _load_script()
    render = tmp_path / "renders"
    candidate = tmp_path / "candidate"
    output = tmp_path / "selected"
    for root in (render, candidate):
        (root / "view-01").mkdir(parents=True)
    base = render / "view-01/base_rgb.png"
    image = candidate / "view-01/unbranded_refined.jpg"
    base.write_bytes(b"base")
    image.write_bytes(b"generated")
    view_set = ViewSet(
        view_set_id="views",
        design_revision="design",
        cameras=(
            Camera(
                view_id="view-01",
                role=ViewRole.OVERALL,
                position=(0, 0, 50),
                target=(1, 1, 0),
                focal_length_mm=35,
                sensor_width_mm=36,
                aspect_ratio="16:9",
            ),
        ),
    )
    path = tmp_path / "views.json"
    path.write_text(view_set.model_dump_json(), encoding="utf-8")
    (candidate / "viewset_generation_manifest.json").write_text(
        json.dumps({"master_sha256": "identity"}), encoding="utf-8"
    )
    (candidate / "view_audit.json").write_text(
        json.dumps(
            {
                "view_set_id": "views",
                "views": [
                    {
                        "view_id": "view-01",
                        "status": audit_status,
                        "image_sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
                        "base_sha256": hashlib.sha256(base.read_bytes()).hexdigest(),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    for name in ("GeminiViewJudge", "GeminiSelectionJudge", "GeminiArtefactJudge"):
        monkeypatch.setattr(
            module,
            name,
            lambda *_: SimpleNamespace(
                proof=lambda *args, **kwargs: SimpleNamespace(status="pass"),
                choose=lambda *args: SimpleNamespace(best_index=None),
            ),
        )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "select",
            str(render),
            "--candidate",
            str(candidate),
            "--view-set",
            str(path),
            "--output",
            str(output),
        ],
    )
    assert module.main() == 2
    assert not list(output.rglob("*.jpg"))
    assert json.loads((output / "selection.json").read_text())["status"] == "blocked"


def test_independent_design_masters_cannot_be_mixed(tmp_path, monkeypatch):
    module = _load_script()
    roots = [tmp_path / "one", tmp_path / "two"]
    for root, identity in zip(roots, ("master-one", "master-two"), strict=True):
        root.mkdir()
        (root / "viewset_generation_manifest.json").write_text(
            json.dumps({"master_sha256": identity}), encoding="utf-8"
        )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "select",
            str(tmp_path),
            "--candidate",
            str(roots[0]),
            "--candidate",
            str(roots[1]),
            "--view-set",
            str(tmp_path / "views.json"),
            "--output",
            str(tmp_path / "selected"),
        ],
    )
    with pytest.raises(SystemExit, match="cannot be mixed"):
        module.main()
