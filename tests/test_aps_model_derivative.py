from pathlib import Path

import httpx

from v365_archviz.config import Settings
from v365_archviz.providers.aps.model_derivative import ApsModelDerivativeClient


def _settings() -> Settings:
    return Settings(
        environment="test",
        artifact_dir=Path(".artifacts"),
        log_level="INFO",
        gemini_api_key=None,
        gemini_image_model="unused",
        gemini_store_interactions=False,
        aps_client_id="client-id",
        aps_client_secret="client-secret",
        aps_base_url="https://aps.test",
        aps_region="US",
        aps_bucket_key="transient-bucket",
    )


def test_complete_signed_upload_and_translation_flow(tmp_path: Path) -> None:
    source = tmp_path / "sample.rvt"
    source.write_bytes(b"rvt payload")
    requests: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, request.url.path))
        path = request.url.path
        if path == "/authentication/v2/token":
            return httpx.Response(200, json={"access_token": "token"})
        if path == "/oss/v2/buckets" and request.method == "POST":
            return httpx.Response(409)
        if path.endswith("/details"):
            return httpx.Response(200, json={"policyKey": "transient"})
        if path.endswith("/signeds3upload") and request.method == "GET":
            return httpx.Response(
                200,
                json={"uploadKey": "upload-1", "urls": ["https://s3.test/part-1"]},
            )
        if request.url.host == "s3.test":
            assert request.content == b"rvt payload"
            return httpx.Response(200)
        if path.endswith("/signeds3upload") and request.method == "POST":
            return httpx.Response(
                200,
                json={"objectId": "urn:adsk.objects:os.object:bucket/sample.rvt"},
            )
        if path == "/modelderivative/v2/designdata/job":
            return httpx.Response(200, json={"result": "success"})
        if path.endswith("/manifest"):
            return httpx.Response(
                200,
                json={
                    "status": "success",
                    "progress": "complete",
                    "derivatives": [{"role": "ifc", "urn": "derivative.ifc"}],
                },
            )
        if "/manifest/derivative.ifc" in path:
            return httpx.Response(200, content=b"ISO-10303-21;\nEND-ISO-10303-21;")
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        client = ApsModelDerivativeClient(_settings(), client=http_client, sleep=lambda _: None)
        client.ensure_transient_bucket()
        uploaded = client.upload(source)
        client.submit_ifc_translation(uploaded.encoded_urn)
        translation = client.wait_for_ifc(uploaded.encoded_urn, poll_interval_seconds=0)
        derivative = client.download_derivative(translation)

    assert uploaded.size_bytes == len(b"rvt payload")
    assert translation.status == "success"
    assert derivative.startswith(b"ISO-10303-21;")
    assert requests.count(("POST", "/authentication/v2/token")) == 1
