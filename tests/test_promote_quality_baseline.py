import json
from pathlib import Path

from PIL import Image

from v365_archviz.api import _with_active_quality_baseline
from v365_archviz.application.promote_quality_baseline import PromoteQualityBaseline


def test_promotes_approved_masters_as_geometry_safe_active_baseline(tmp_path: Path) -> None:
    generated = tmp_path / "generated" / "model" / "design"
    for view_id, color in (("view-02", "green"), ("view-04", "white")):
        view = generated / view_id
        view.mkdir(parents=True)
        Image.new("RGB", (64, 36), color).save(view / "unbranded_refined.jpg")
    (generated / "design_master_review.json").write_text(
        json.dumps(
            {
                "approved": True,
                "master_view_ids": {"site": "view-02", "facade": "view-04"},
            }
        ),
        encoding="utf-8",
    )
    (generated / "final_viewset_review.json").write_text(
        json.dumps({"approved": True}), encoding="utf-8"
    )

    result = PromoteQualityBaseline().execute(
        tmp_path, "model", "design", "model-design-standard-v29"
    )

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["status"] == "active"
    assert set(manifest["reference_ids"]) == {
        "factory_design_reference",
        "context_realism_reference",
    }
    assert "project_geometry" in manifest["influence_contract"]["prohibited"]
    for role, reference_id in result.reference_ids.items():
        metadata = json.loads(
            (tmp_path / "references" / reference_id / "metadata.json").read_text(
                encoding="utf-8"
            )
        )
        assert metadata["role"] == role
        assert metadata["source"] == "approved_viewset_baseline"
        assert "project_geometry" in metadata["prohibited_influence"]

    refs, roles = _with_active_quality_baseline(tmp_path, (), ())
    assert len(refs) == 2
    assert set(roles) == {
        "factory_design_reference",
        "context_realism_reference",
    }

    explicit_facade = refs[roles.index("factory_design_reference")]
    refs, roles = _with_active_quality_baseline(
        tmp_path, (explicit_facade,), ("factory_design_reference",)
    )
    assert roles.count("factory_design_reference") == 1
    assert roles.count("context_realism_reference") == 1
