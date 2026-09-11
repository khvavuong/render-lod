from __future__ import annotations

import base64
import io
from pathlib import Path

import httpx
import pytest
from PIL import Image

from v365_archviz.config import Settings
from v365_archviz.errors import ConfigurationError
from v365_archviz.providers.contracts import ViewConditioningInput, ViewSetGenerationInput
from v365_archviz.providers.image_factory import create_image_renderer
from v365_archviz.providers.openai_image import OpenAIImageRenderer


def _settings(**changes: object) -> Settings:
    values: dict[str, object] = {
        "environment": "test",
        "artifact_dir": Path(".artifacts"),
        "log_level": "INFO",
        "gemini_api_key": "gemini-secret",
        "gemini_image_model": "gemini-model",
        "gemini_store_interactions": False,
        "aps_client_id": None,
        "aps_client_secret": None,
        "aps_base_url": "https://developer.api.autodesk.com",
        "aps_region": "US",
        "aps_bucket_key": None,
        "openai_api_key": "openai-secret",
    }
    values.update(changes)
    return Settings(**values)  # type: ignore[arg-type]


def _png(size: tuple[int, int] = (30, 20), color: str = "white") -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, format="PNG")
    return buffer.getvalue()


def _view(image: Path, view_id: str) -> ViewConditioningInput:
    return ViewConditioningInput(
        view_id=view_id,
        base_rgb=image,
        depth=image,
        instance_id=image,
        semantic=image,
        edges=image,
        prompt=f"Refine {view_id}",
    )


def test_design_master_is_attached_after_current_geometry_image(tmp_path: Path) -> None:
    base = tmp_path / "base.png"
    base.write_bytes(_png())
    calls: list[bytes] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.content)
        assert request.headers["authorization"] == "Bearer openai-secret"
        assert b'name="model"' in request.content
        assert b"gpt-image-2.5-sunburst" in request.content
        assert b'name="quality"' in request.content
        assert b'name="image[]"' in request.content
        return httpx.Response(
            200,
            headers={"x-request-id": f"req-{len(calls)}"},
            json={"data": [{"b64_json": base64.b64encode(_png()).decode()}]},
        )

    generation = ViewSetGenerationInput(
        request_id="generation-1",
        project_id="project-1",
        model_revision="model-1",
        design_revision="design-1",
        view_set_id="views-1",
        profile="preview_fast",
        views=(_view(base, "view-03"), _view(base, "view-01"), _view(base, "view-02")),
        identity_prompt="One immutable cream and graphite facade family.",
    )
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        renderer = OpenAIImageRenderer(_settings(), client=client)
        result = renderer.generate_view_set(generation)

    assert [view.view_id for view in result.views] == ["view-03", "view-01", "view-02"]
    assert len(calls) == 3
    assert calls[0].count(b'name="image[]"') == 1
    assert calls[1].count(b'name="image[]"') == 2
    assert calls[2].count(b'name="image[]"') == 2
    assert b"Design Master" not in calls[0]
    assert b"Design Master" in calls[1]
    with Image.open(io.BytesIO(result.views[0].image.content)) as output:
        assert output.size == (30, 17)


def test_factory_keeps_gemini_as_configurable_pipeline_provider() -> None:
    renderer = create_image_renderer(_settings(image_provider="gemini"))
    try:
        assert renderer.name == "gemini-photoreal_balanced"
    finally:
        renderer.close()


def test_openai_provider_requires_its_own_key() -> None:
    with pytest.raises(ConfigurationError, match="OPENAI_API_KEY"):
        create_image_renderer(_settings(image_provider="openai-image", openai_api_key=None))
