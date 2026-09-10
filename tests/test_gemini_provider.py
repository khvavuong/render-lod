import base64
from pathlib import Path

import httpx
from PIL import Image

from v365_archviz.config import Settings
from v365_archviz.providers.contracts import ViewConditioningInput, ViewSetGenerationInput
from v365_archviz.providers.gemini import (
    GeminiConditioningMode,
    GeminiImageRenderer,
    _image_block,
    _neutral_semantic_block,
)


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
    Image.new("RGB", (2, 2), "white").save(image)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["x-goog-api-key"] == "test-secret"
        body = __import__("json").loads(request.content)
        assert body["store"] is False
        assert len(body["input"]) == 11
        prompt = body["input"][0]["text"]
        assert "non-binding realism samples only" in prompt
        assert "Do not copy their palette" in prompt
        labels = [block["text"] for block in body["input"] if block["type"] == "text"]
        assert any("sole camera" in label for label in labels)
        assert any("STRUCTURAL EDGES" in label for label in labels)
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
        assert renderer.capabilities.supports_masked_edit is False
        assert renderer.capabilities.supports_multi_reference is True
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


def test_minimal_conditioning_sends_only_base_edges_and_references(tmp_path: Path) -> None:
    image = tmp_path / "pass.png"
    Image.new("RGB", (2, 2), "white").save(image)

    def handler(request: httpx.Request) -> httpx.Response:
        body = __import__("json").loads(request.content)
        assert len(body["input"]) == 5
        labels = [block["text"] for block in body["input"] if block["type"] == "text"]
        assert any("base RGB, structural edges" in label for label in labels)
        assert not any("DEPTH" in label for label in labels)
        assert not any("INSTANCE ID" in label for label in labels)
        assert not any("SEMANTIC ID" in label for label in labels)
        return httpx.Response(
            200,
            json={
                "id": "interaction-minimal",
                "output": {
                    "mime_type": "image/jpeg",
                    "data": base64.b64encode(b"output-image").decode(),
                },
            },
        )

    request_input = ViewConditioningInput(
        view_id="view-01",
        base_rgb=image,
        depth=image,
        instance_id=image,
        semantic=image,
        edges=image,
        prompt="Refine this shared-scene render.",
    )
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        renderer = GeminiImageRenderer(
            _settings(),
            client=client,
            conditioning_mode=GeminiConditioningMode.MINIMAL,
        )
        result = renderer.generate(request_input)

    assert renderer.name == "gemini-minimal"
    assert result.provider_request_id == "interaction-minimal"


def test_semantic_block_is_neutral_grayscale(tmp_path: Path) -> None:
    semantic = tmp_path / "semantic.png"
    Image.new("RGB", (2, 1), "red").save(semantic)

    block = _neutral_semantic_block(semantic)

    with Image.open(__import__("io").BytesIO(base64.b64decode(block["data"]))) as decoded:
        red = decoded.convert("RGB").getpixel((0, 0))
    assert red[0] == red[1] == red[2]


def test_marketing_viewset_uses_overall_view_as_design_master(tmp_path: Path) -> None:
    image = tmp_path / "pass.png"
    Image.new("RGB", (2, 2), "white").save(image)
    calls: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = __import__("json").loads(request.content)
        calls.append(body)
        index = len(calls)
        return httpx.Response(
            200,
            json={
                "id": f"interaction-{index}",
                "output": {
                    "mime_type": "image/jpeg",
                    "data": base64.b64encode(f"output-{index}".encode()).decode(),
                },
            },
        )

    def view(view_id: str) -> ViewConditioningInput:
        return ViewConditioningInput(
            view_id=view_id,
            base_rgb=image,
            depth=image,
            instance_id=image,
            semantic=image,
            edges=image,
            prompt="Refine this shared-scene render.",
        )

    generation_request = ViewSetGenerationInput(
        request_id="generation-1",
        project_id="project-1",
        model_revision="model-1",
        design_revision="design-1",
        view_set_id="views-1",
        profile="marketing_hero",
        views=(view("view-03"), view("view-01"), view("view-02")),
    )
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        renderer = GeminiImageRenderer(_settings(), client=client)
        result = renderer.generate_view_set(generation_request)

    assert [generated.view_id for generated in result.views] == [
        "view-03",
        "view-01",
        "view-02",
    ]
    assert len(calls) == 3
    assert "STYLE ANCHOR" not in calls[0]["input"][0]["text"]  # type: ignore[index]
    assert calls[1]["input"][-1]["data"] == base64.b64encode(b"output-1").decode()  # type: ignore[index]
    assert calls[2]["input"][-1]["data"] == base64.b64encode(b"output-1").decode()  # type: ignore[index]
    assert "STYLE ANCHOR" in calls[1]["input"][0]["text"]  # type: ignore[index]
