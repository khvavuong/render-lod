from fastapi.testclient import TestClient

from v365_archviz.api import app
from v365_archviz.domain.scene import CanonicalScene

client = TestClient(app)


def test_health_endpoint() -> None:
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_capabilities_never_expose_credentials(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("GEMINI_API_KEY", "secret-value")
    response = client.get("/v1/system/capabilities")

    assert response.status_code == 200
    assert response.json()["gemini_image_generation"] is True
    assert "secret-value" not in response.text


def test_design_revision_and_view_set_are_idempotent(
    tmp_path,
    monkeypatch,
    valid_scene: CanonicalScene,  # type: ignore[no-untyped-def]
) -> None:
    monkeypatch.setenv("V365_ARTIFACT_DIR", str(tmp_path))
    model_revision = "model-revision"
    scene_path = tmp_path / "scenes" / model_revision / "canonical_scene.json"
    scene_path.parent.mkdir(parents=True)
    scene_path.write_text(valid_scene.model_dump_json(), encoding="utf-8")
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
    view_set_id = first.json()["view_set_id"]
    status_response = client.get(f"/v1/view-sets/{view_set_id}")
    assert status_response.status_code == 200
    assert status_response.json()["job_id"] == first.json()["job_id"]
    assert (tmp_path / "metadata" / "jobs" / f"{first.json()['job_id']}.json").is_file()


def test_api_rejects_revision_path_traversal(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("V365_ARTIFACT_DIR", str(tmp_path))

    response = client.post(
        "/v1/projects/project/design-revisions",
        json={"model_revision": "..", "brief": {}},
    )

    assert response.status_code == 422
    assert not (tmp_path.parent / "canonical_scene.json").exists()
