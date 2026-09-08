from fastapi.testclient import TestClient

from v365_archviz.api import app


def test_health_endpoint() -> None:
    response = TestClient(app).get("/healthz")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_capabilities_never_expose_credentials(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("GEMINI_API_KEY", "secret-value")
    response = TestClient(app).get("/v1/system/capabilities")

    assert response.status_code == 200
    assert response.json()["gemini_image_generation"] is True
    assert "secret-value" not in response.text

