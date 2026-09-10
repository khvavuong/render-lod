from pathlib import Path

import httpx
from PIL import Image

from v365_archviz.config import Settings
from v365_archviz.providers.contracts import ViewConditioningInput
from v365_archviz.providers.stability import StabilityStructureRenderer


def _settings() -> Settings:
    return Settings(
        environment="test",
        artifact_dir=Path(".artifacts"),
        log_level="INFO",
        gemini_api_key=None,
        gemini_image_model="gemini-3.1-flash-image",
        gemini_store_interactions=False,
        aps_client_id=None,
        aps_client_secret=None,
        aps_base_url="https://developer.api.autodesk.com",
        aps_region="US",
        aps_bucket_key=None,
        stability_api_key="stability-test-secret",
        stability_control_strength=0.88,
        stability_seed=1234,
    )


def test_structure_request_has_control_strength_seed_and_safe_headers(tmp_path: Path) -> None:
    image = tmp_path / "control.png"
    Image.new("RGB", (64, 64), "white").save(image)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer stability-test-secret"
        assert request.headers["accept"] == "image/*"
        body = request.content
        assert b'name="image"' in body
        assert b'name="control_strength"' in body
        assert b"0.88" in body
        assert b'name="seed"' in body
        assert b'name="style_preset"' in body
        assert b"photographic" in body
        return httpx.Response(
            200,
            content=b"jpeg-output",
            headers={
                "content-type": "image/jpeg",
                "stability-request-id": "stability-request-1",
            },
        )

    request_input = ViewConditioningInput(
        view_id="view-01",
        base_rgb=image,
        depth=image,
        instance_id=image,
        semantic=image,
        edges=image,
        prompt="Photorealistic industrial architecture.",
    )
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        renderer = StabilityStructureRenderer(_settings(), client=client)
        result = renderer.generate(request_input)

    assert renderer.capabilities.supports_control_scale is True
    assert renderer.provenance["control_strength"] == 0.88
    assert result.content == b"jpeg-output"
    assert result.provider_request_id == "stability-request-1"
