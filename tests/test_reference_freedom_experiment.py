import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


def load_script(name):
    path = Path(__file__).resolve().parents[1] / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_treatments_add_only_the_intended_authority(tmp_path):
    module = load_script("run_reference_freedom_experiment")
    camera = tmp_path / "camera.json"
    camera.write_text("{}")
    base = tmp_path / "base.png"
    base.write_bytes(b"base")
    reference = tmp_path / "ref.png"
    reference.write_bytes(b"reference")
    config = {
        "brief": "Common architectural brief",
        "image_size": "2K",
        "aspect_ratio": "16:9",
        "references": [
            {"path": str(reference), "role": "architecture", "instruction": "Learn architecture"}
        ],
        "views": {
            "aerial": {"intent": "Choose a good aerial", "base": str(base), "camera": str(camera)}
        },
    }
    contract = {
        "source_focus_elements": [{"role": "main_shed"}],
        "unapproved_pipeline_programme": {"loading_doors": 6},
    }
    samples = [module.build_sample(config, arm, "aerial", contract, "model") for arm in module.ARMS]
    assert "MEASURED SOURCE" not in samples[0]["prompt"]
    assert "MEASURED SOURCE" in samples[1]["prompt"]
    assert len(samples[0]["images"]) == len(samples[1]["images"]) == 1
    assert len(samples[2]["images"]) == len(samples[3]["images"]) == 2
    assert samples[3]["prompt"].startswith(samples[2]["prompt"])
    assert "EXPERIMENTAL PROGRAMME LOCK" not in samples[2]["prompt"]
    assert "EXPERIMENTAL PROGRAMME LOCK" in samples[3]["prompt"]
    assert all(sample["model"] == "model" and sample["store"] is False for sample in samples)
    with pytest.raises(ValueError, match="unknown treatment"):
        module.build_sample(config, "unregistered", "aerial", contract, "model")


def test_shortlist_does_not_approve_unknown_or_defective_scores():
    module = load_script("review_reference_freedom_experiment")
    verdict = dict(composition=4, design=4, realism=4, material_lighting=4, critical_defects=[])
    assert module.quality_shortlist(verdict)
    assert not module.quality_shortlist({**verdict, "design": None})
    assert not module.quality_shortlist({**verdict, "design": True})
    assert not module.quality_shortlist({**verdict, "critical_defects": ["broken truck"]})


def test_failed_review_is_unknown_without_another_provider_call(tmp_path):
    module = load_script("review_reference_freedom_experiment")
    cache = tmp_path / "review.json"
    fingerprint = hashlib.sha256(
        json.dumps({"model": "model", "blocks": []}, sort_keys=True).encode()
    ).hexdigest()
    module.write_json(cache, {"status": "failed", "request_signature": fingerprint})
    verdict = module.advisory_judge(None, "model", "not-a-real-key", [], cache)
    assert verdict["review_status"] == "unavailable"
    assert not module.quality_shortlist(verdict)
    assert json.loads(cache.read_text())["status"] == "failed"


def test_stale_review_integrity_failure_is_not_hidden_as_unknown(tmp_path):
    module = load_script("review_reference_freedom_experiment")
    cache = tmp_path / "review.json"
    module.write_json(cache, {"status": "complete", "request_signature": "different"})
    with pytest.raises(ValueError, match="stale review"):
        module.advisory_judge(None, "model", "not-a-real-key", [], cache)
