import json
from pathlib import Path

from fastapi.testclient import TestClient

from v365_archviz.api import app
from v365_archviz.domain.jobs import GenerationJob
from v365_archviz.domain.scene import CanonicalScene
from v365_archviz.domain.workflow import (
    Camera,
    GenerationProfile,
    ViewRole,
    ViewSet,
    WorkflowState,
)
from v365_archviz.providers.local_jobs import LocalJobRepository

client = TestClient(app)


def test_health_endpoint() -> None:
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_design_options_are_served_from_a_versioned_backend_catalog() -> None:
    response = client.get("/v1/design-options")

    assert response.status_code == 200
    payload = response.json()
    assert payload["catalog_version"] == "industrial-intent-v2"
    assert payload["design_packages"]
    assert payload["gate_kits"]
    assert {item["value"] for item in payload["styles"]} >= {
        "contemporary_industrial",
        "corporate_industrial",
    }


def test_brand_logo_is_served_as_png() -> None:
    response = client.get("/v1/brand/logo")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"


def test_uploads_and_inspects_rvt_model(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("V365_ARTIFACT_DIR", str(tmp_path))
    monkeypatch.setenv("APS_BUCKET_KEY", "")
    source = Path("resource/model_lod100_sample.rvt")

    response = client.post(
        "/v1/models",
        content=source.read_bytes(),
        headers={
            "Content-Type": "application/octet-stream",
            "X-Filename": "factory.rvt",
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["file_name"] == "factory.rvt"
    assert payload["size_bytes"] == source.stat().st_size
    assert payload["ready"] is False
    assert (tmp_path / "uploads" / payload["model_revision"] / "source.rvt").is_file()
    assert (tmp_path / "inspections" / payload["model_revision"] / "manifest.json").is_file()


def test_upload_prepares_uncached_model_when_aps_is_configured(
    tmp_path,
    monkeypatch,
    valid_scene: CanonicalScene,  # type: ignore[no-untyped-def]
) -> None:
    monkeypatch.setenv("V365_ARTIFACT_DIR", str(tmp_path))
    monkeypatch.setenv("APS_CLIENT_ID", "client")
    monkeypatch.setenv("APS_CLIENT_SECRET", "secret")
    monkeypatch.setenv("APS_BUCKET_KEY", "bucket")
    prepared: list[Path] = []

    def prepare(source: Path, settings: object) -> None:
        del settings
        prepared.append(source)
        scene = tmp_path / "scenes" / source.parent.name / "canonical_scene.json"
        scene.parent.mkdir(parents=True)
        scene.write_text(valid_scene.model_dump_json(), encoding="utf-8")

    monkeypatch.setattr("v365_archviz.api._prepare_uploaded_model", prepare)
    source = Path("resource/model_lod100_sample.rvt")

    response = client.post(
        "/v1/models",
        content=source.read_bytes(),
        headers={
            "Content-Type": "application/octet-stream",
            "X-Filename": "new-factory.rvt",
        },
    )

    assert response.status_code == 201
    assert response.json()["ready"] is True
    assert len(prepared) == 1
    assert prepared[0].name == "source.rvt"


def test_capabilities_never_expose_credentials(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("GEMINI_API_KEY", "secret-value")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-secret-value")
    response = client.get("/v1/system/capabilities")

    assert response.status_code == 200
    assert response.json()["gemini_image_generation"] is True
    assert response.json()["openai_image_generation"] is True
    assert "secret-value" not in response.text
    assert "openai-secret-value" not in response.text


def test_model_capabilities_and_preview_are_semantic_evidence_gated(
    tmp_path,
    monkeypatch,
    valid_scene: CanonicalScene,  # type: ignore[no-untyped-def]
) -> None:
    monkeypatch.setenv("V365_ARTIFACT_DIR", str(tmp_path))
    model_revision = "capability-model"
    scene_path = tmp_path / "scenes" / model_revision / "canonical_scene.json"
    scene_path.parent.mkdir(parents=True)
    scene_path.write_text(valid_scene.model_dump_json(), encoding="utf-8")

    capabilities = client.get(f"/v1/models/{model_revision}/design-capabilities")
    assert capabilities.status_code == 200
    by_key = {item["key"]: item for item in capabilities.json()["components"]}
    assert by_key["envelope"]["supported"] is True
    assert by_key["office_entrance"]["supported"] is True
    assert by_key["gate"]["supported"] is False

    preview = client.post(
        f"/v1/models/{model_revision}/design-preview",
        json={
            "project_id": "factory-01",
            "intent": {
                "gate_kit": "industrial_sliding",
                "office_entrance_kit": "framed_glazed_bay",
            },
        },
    )
    assert preview.status_code == 200
    payload = preview.json()
    assert len(payload["preview_token"]) == 64
    assert payload["normalized_intent"]["gate_kit"] == "preserve_model"
    assert payload["normalized_intent"]["office_entrance_kit"] == "framed_glazed_bay"
    assert {warning["field"] for warning in payload["warnings"]} >= {"gate_kit"}

    stale = client.post(
        "/v1/projects/factory-01/design-revisions",
        json={
            "model_revision": model_revision,
            "preview_token": payload["preview_token"],
            "intent": {
                "gate_kit": "industrial_sliding",
                "office_entrance_kit": "framed_glazed_bay",
                "accent_coverage_percent": 8,
            },
        },
    )
    assert stale.status_code == 409
    assert "changed after preview" in stale.json()["detail"]


def test_design_revision_and_view_set_are_idempotent(
    tmp_path,
    monkeypatch,
    valid_scene: CanonicalScene,  # type: ignore[no-untyped-def]
) -> None:
    monkeypatch.setenv("V365_ARTIFACT_DIR", str(tmp_path))
    monkeypatch.setenv("V365_ENABLE_LOCAL_WORKER", "1")
    dispatched: list[str] = []
    monkeypatch.setattr(
        "v365_archviz.api._generation_dispatcher.submit",
        lambda job_id: dispatched.append(job_id) or True,
    )
    model_revision = "model-revision"
    scene_path = tmp_path / "scenes" / model_revision / "canonical_scene.json"
    scene_path.parent.mkdir(parents=True)
    scene_path.write_text(valid_scene.model_dump_json(), encoding="utf-8")

    model_response = client.get("/v1/models/latest")
    assert model_response.status_code == 200
    assert model_response.json()["model_revision"] == model_revision
    brief = {
        "project_id": "project-1",
        "design_language": {
            "style": "clean industrial",
            "primary_material": "light metal",
            "secondary_material": "dark metal",
            "office_material": "glass",
        },
        "environment": {
            "time": "09:30",
            "weather": "clear",
            "sun_azimuth_deg": 135,
            "sun_elevation_deg": 45,
            "white_balance_k": 5600,
        },
        "panel_module_m": 1.2,
        "roof_type": "preserve source",
        "grammar_version": "grammar-v1",
        "asset_library_version": "assets-v1",
    }

    design_response = client.post(
        "/v1/projects/project-1/design-revisions",
        json={"model_revision": model_revision, "brief": brief},
    )

    assert design_response.status_code == 201
    design_revision = design_response.json()["design_revision"]
    endpoint = f"/v1/design-revisions/{design_revision}/view-sets"
    first = client.post(endpoint, json={"model_revision": model_revision})
    second = client.post(endpoint, json={"model_revision": model_revision})
    assert first.status_code == 202
    assert first.json()["created"] is True
    assert first.json()["state"] == "rendering_passes"
    assert second.status_code == 202
    assert second.json()["created"] is False
    assert dispatched == [first.json()["job_id"], first.json()["job_id"]]
    view_set_id = first.json()["view_set_id"]
    status_response = client.get(f"/v1/view-sets/{view_set_id}")
    assert status_response.status_code == 200
    assert status_response.json()["job_id"] == first.json()["job_id"]
    assert (tmp_path / "metadata" / "jobs" / f"{first.json()['job_id']}.json").is_file()

    generated = tmp_path / "generated" / model_revision / design_revision
    image_path = generated / "view-01" / "refined.jpg"
    image_path.parent.mkdir(parents=True)
    image_path.write_bytes(b"generated-image")
    (generated / "viewset_board.jpg").write_bytes(b"viewset-board")
    video = tmp_path / "videos" / model_revision / design_revision / "video-plan" / "showreel.mp4"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"showreel")

    output_response = client.get(f"/v1/view-sets/{view_set_id}/outputs")
    assert output_response.status_code == 200
    assert [item["id"] for item in output_response.json()["outputs"]] == [
        "image-view-01",
        "board",
        "video",
    ]
    image_response = client.get(f"/v1/view-sets/{view_set_id}/outputs/image-view-01")
    assert image_response.status_code == 200
    assert image_response.content == b"generated-image"


def test_review_approval_resumes_board_worker(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("V365_ARTIFACT_DIR", str(tmp_path))
    monkeypatch.setenv("V365_ENABLE_LOCAL_WORKER", "1")
    dispatched: list[str] = []
    monkeypatch.setattr(
        "v365_archviz.api._generation_dispatcher.submit",
        lambda job_id: dispatched.append(job_id) or True,
    )
    repository = LocalJobRepository(tmp_path / "metadata")
    job = GenerationJob.create(
        job_id="job-review",
        idempotency_key="key-review",
        project_id="project",
        model_revision="model",
        design_revision="design",
        view_set_id="view-set-review",
        profile=GenerationProfile.MARKETING_HERO,
        initial_state=WorkflowState.VALIDATING,
    ).transition(WorkflowState.HUMAN_REVIEW)
    repository.create_or_get(job)
    qa_path = tmp_path / "generated" / "model" / "design" / "technical_qa.json"
    qa_path.parent.mkdir(parents=True)
    qa_path.write_text('{"passed": true}', encoding="utf-8")

    response = client.post("/v1/view-sets/view-set-review/approve")

    assert response.status_code == 202
    assert response.json()["state"] == "composing_board"
    assert dispatched == ["job-review"]


def test_design_master_approval_resumes_remaining_view_generation(
    tmp_path,
    monkeypatch,  # type: ignore[no-untyped-def]
) -> None:
    monkeypatch.setenv("V365_ARTIFACT_DIR", str(tmp_path))
    monkeypatch.setenv("V365_ENABLE_LOCAL_WORKER", "1")
    dispatched: list[str] = []
    monkeypatch.setattr(
        "v365_archviz.api._generation_dispatcher.submit",
        lambda job_id: dispatched.append(job_id) or True,
    )
    repository = LocalJobRepository(tmp_path / "metadata")
    job = GenerationJob.create(
        job_id="job-master-review",
        idempotency_key="key-master-review",
        project_id="project",
        model_revision="model",
        design_revision="design",
        view_set_id="view-set-master-review",
        profile=GenerationProfile.MARKETING_HERO,
        initial_state=WorkflowState.GENERATING_VIEWSET,
    ).transition(WorkflowState.DESIGN_MASTER_REVIEW)
    repository.create_or_get(job)
    generated = tmp_path / "generated" / "model" / "design"
    master = generated / "view-04" / "refined.jpg"
    master.parent.mkdir(parents=True)
    master.write_bytes(b"master-image")
    review = generated / "design_master_review.json"
    review.write_text(
        json.dumps(
            {
                "status": "pending",
                "approved": False,
                "master_view_id": "view-04",
                "master_image_ref": str(master),
            }
        ),
        encoding="utf-8",
    )

    response = client.post("/v1/view-sets/view-set-master-review/approve")

    assert response.status_code == 202
    assert response.json()["state"] == "generating_viewset"
    assert json.loads(review.read_text())["approved"] is True
    assert dispatched == ["job-master-review"]


def test_failed_job_retries_from_persisted_generated_checkpoint(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("V365_ARTIFACT_DIR", str(tmp_path))
    monkeypatch.setenv("V365_ENABLE_LOCAL_WORKER", "1")
    dispatched: list[str] = []
    monkeypatch.setattr(
        "v365_archviz.api._generation_dispatcher.submit",
        lambda job_id: dispatched.append(job_id) or True,
    )
    repository = LocalJobRepository(tmp_path / "metadata")
    job = GenerationJob.create(
        job_id="job-failed",
        idempotency_key="key-failed",
        project_id="project",
        model_revision="model",
        design_revision="design",
        view_set_id="view-set-failed",
        profile=GenerationProfile.MARKETING_HERO,
        initial_state=WorkflowState.VALIDATING,
    ).transition(
        WorkflowState.FAILED,
        error_code="LegacyQAError",
        error_message="legacy QA failure",
    )
    repository.create_or_get(job)
    generated = tmp_path / "generated" / "model" / "design"
    generated.mkdir(parents=True)
    (generated / "viewset_generation_manifest.json").write_text("{}", encoding="utf-8")
    (generated / "protected_composite_manifest.json").write_text("{}", encoding="utf-8")

    response = client.post("/v1/view-sets/view-set-failed/retry")

    assert response.status_code == 202
    assert response.json()["state"] == "validating"
    assert response.json()["error_message"] is None
    assert dispatched == ["job-failed"]


def test_design_revision_compiles_safe_user_intent(
    tmp_path,
    monkeypatch,
    valid_scene: CanonicalScene,  # type: ignore[no-untyped-def]
) -> None:
    monkeypatch.setenv("V365_ARTIFACT_DIR", str(tmp_path))
    model_revision = "intent-model"
    scene_path = tmp_path / "scenes" / model_revision / "canonical_scene.json"
    scene_path.parent.mkdir(parents=True)
    scene_path.write_text(valid_scene.model_dump_json(), encoding="utf-8")

    response = client.post(
        "/v1/projects/factory-01/design-revisions",
        json={
            "model_revision": model_revision,
            "intent": {
                "style_preset": "minimal_industrial",
                "decor_level": "subtle",
                "free_text": ("Xóa đường nội bộ. Ưu tiên tôn có độ nhám và ánh sáng tự nhiên."),
            },
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["preset_catalog_version"] == "industrial-intent-v2"
    assert payload["normalized_intent"]["free_text"] == (
        "Ưu tiên tôn có độ nhám và ánh sáng tự nhiên."
    )
    assert payload["warnings"][0]["code"] == "locked_geometry_override_ignored"
    target = tmp_path / "scenes" / model_revision / "designs" / payload["design_revision"]
    assert (target / "render_intent.json").is_file()
    assert (target / "intent_compilation.json").is_file()
    design = json.loads((target / "design_dna.json").read_text(encoding="utf-8"))
    assert design["design_preferences"]["style_preset"] == "minimal_industrial"
    assert design["design_preferences"]["decor_level"] == "subtle"
    assert "độ nhám" in design["design_preferences"]["creative_prompt"]
    assert design["site_design"]["surrounding_context_mode"] == "conceptual_industrial_park"
    assert design["industrial_context"]["mode"] == "conceptual_industrial_park"


def test_api_rejects_revision_path_traversal(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("V365_ARTIFACT_DIR", str(tmp_path))

    response = client.post(
        "/v1/projects/project/design-revisions",
        json={"model_revision": "..", "brief": {}},
    )

    assert response.status_code == 422
    assert not (tmp_path.parent / "canonical_scene.json").exists()


def test_video_generation_is_an_explicit_idempotent_job(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("V365_ARTIFACT_DIR", str(tmp_path))
    monkeypatch.setenv("V365_ENABLE_LOCAL_WORKER", "1")
    dispatched: list[str] = []
    monkeypatch.setattr(
        "v365_archviz.api._video_dispatcher.submit",
        lambda job_id: dispatched.append(job_id) or True,
    )
    image_job = GenerationJob.create(
        job_id="image-job",
        idempotency_key="image-key",
        project_id="project",
        model_revision="model",
        design_revision="design",
        view_set_id="viewset",
        profile=GenerationProfile.MARKETING_HERO,
        initial_state=WorkflowState.COMPLETED,
    )
    repository = LocalJobRepository(tmp_path / "metadata")
    repository.create_or_get(image_job)
    generated = tmp_path / "generated" / "model" / "design"
    generated.mkdir(parents=True)
    (generated / "viewset_generation_manifest.json").write_text("{}", encoding="utf-8")
    (generated / "viewset_board.jpg").write_bytes(b"board")
    cameras = tuple(
        Camera(
            view_id=f"view-{index:02d}",
            role=ViewRole.OVERALL,
            position=(10.0, 10.0, 10.0),
            target=(0.0, 0.0, 0.0),
            focal_length_mm=35,
            sensor_width_mm=36,
            aspect_ratio="16:9",
        )
        for index in range(1, 7)
    )
    view_set_path = tmp_path / "scenes" / "model" / "designs" / "design" / "view_set.json"
    view_set_path.parent.mkdir(parents=True)
    view_set_path.write_text(
        ViewSet(view_set_id="viewset", design_revision="design", cameras=cameras).model_dump_json(),
        encoding="utf-8",
    )
    for camera in cameras:
        source = generated / camera.view_id / "provider_source.jpg"
        source.parent.mkdir(parents=True)
        source.write_bytes(b"image")

    first = client.post("/v1/view-sets/viewset/video-jobs")
    second = client.post("/v1/view-sets/viewset/video-jobs")

    assert first.status_code == 202
    assert first.json()["created"] is True
    assert first.json()["state"] == "queued"
    assert first.json()["estimated_cost_usd"] == 1.2
    assert second.status_code == 202
    assert second.json()["created"] is False
    assert dispatched == [first.json()["video_job_id"], first.json()["video_job_id"]]
    assert repository.get("image-job").state is WorkflowState.COMPLETED


def test_video_job_rejects_an_incomplete_image_set(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("V365_ARTIFACT_DIR", str(tmp_path))
    image_job = GenerationJob.create(
        job_id="image-job",
        idempotency_key="image-key",
        project_id="project",
        model_revision="model",
        design_revision="design",
        view_set_id="viewset",
        profile=GenerationProfile.MARKETING_HERO,
        initial_state=WorkflowState.GENERATING_VIEWSET,
    )
    LocalJobRepository(tmp_path / "metadata").create_or_get(image_job)

    response = client.post("/v1/view-sets/viewset/video-jobs")

    assert response.status_code == 409
    assert "must complete" in response.json()["detail"]
