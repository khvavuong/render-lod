import base64
from pathlib import Path

import httpx
from PIL import Image

from v365_archviz.config import Settings
from v365_archviz.providers.contracts import ViewConditioningInput
from v365_archviz.providers.gemini import GeminiImageRenderer, _image_block


def _settings() -> Settings:
    return Settings(
        environment="test",
        artifact_dir=Path(".artifacts"),
        log_level="INFO",
        gemini_api_key="test-secret",
        gemini_image_model="gemini-3.1-flash-image",
        gemini_store_interactions=False,
        aps_client_id=None,
        aps_client_secret=None,
        aps_base_url="https://developer.api.autodesk.com",
        aps_region="US",
        aps_bucket_key=None,
    )


def test_generates_with_privacy_safe_request(tmp_path: Path) -> None:
    image = tmp_path / "pass.png"
    image.write_bytes(b"fake-png")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["x-goog-api-key"] == "test-secret"
        body = __import__("json").loads(request.content)
        assert body["store"] is False
        assert len(body["input"]) == 6
        prompt = body["input"][0]["text"]
        assert "non-binding realism samples only" in prompt
        assert "Do not copy their palette" in prompt
        return httpx.Response(
            200,
            json={
                "id": "interaction-1",
                "steps": [
                    {
                        "content": [
                            {
                                "mime_type": "image/jpeg",
                                "data": base64.b64encode(b"output-image").decode(),
                            }
                        ]
                    }
                ],
            },
        )

    request = ViewConditioningInput(
        view_id="view-01",
        base_rgb=image,
        depth=image,
        instance_id=image,
        semantic=image,
        edges=image,
        prompt="Refine this shared-scene render.",
    )
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        renderer = GeminiImageRenderer(_settings(), client=client)
        result = renderer.generate(request)

    assert result.content == b"output-image"
    assert result.media_type == "image/jpeg"
    assert result.provider_request_id == "interaction-1"


def test_image_block_detects_content_mime_instead_of_misleading_suffix(
    tmp_path: Path,
) -> None:
    reference = tmp_path / "reference.png"
    Image.new("RGB", (2, 2), "white").save(reference, format="JPEG")

    block = _image_block(reference)

    assert block["mime_type"] == "image/jpeg"
