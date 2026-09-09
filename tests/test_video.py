from __future__ import annotations

import base64
import json
from pathlib import Path

import httpx
import pytest
from PIL import Image
from pydantic import ValidationError

from v365_archviz.config import Settings
from v365_archviz.domain.video import VideoPlan, VideoShot
from v365_archviz.providers.contracts import VideoGenerationInput
from v365_archviz.providers.veo import VeoVideoRenderer


def _settings() -> Settings:
    return Settings(
        environment="test",
        artifact_dir=Path(".artifacts"),
        log_level="INFO",
        gemini_api_key="secret",
        gemini_image_model="unused",
        gemini_store_interactions=False,
        aps_client_id=None,
        aps_client_secret=None,
        aps_base_url="https://developer.api.autodesk.com",
        aps_region="US",
        aps_bucket_key=None,
    )


def _shot(image: Path) -> VideoShot:
    return VideoShot(
        shot_id="shot-01",
        view_id="view-01",
        source_image_ref=str(image),
        prompt="Slow stable push forward while preserving exact architecture.",
        negative_prompt="geometry drift",
        duration_seconds=4,
        aspect_ratio="16:9",
        resolution="720p",
        seed=42,
    )


def test_video_plan_rejects_cost_above_budget(tmp_path: Path) -> None:
    image = tmp_path / "source.jpg"
    Image.new("RGB", (16, 9), "white").save(image)
    with pytest.raises(ValidationError, match="exceeds budget"):
        VideoPlan(
            plan_id="video-1",
            project_id="project-1",
            model_revision="model-1",
            design_revision="design-1",
            view_set_id="views-1",
            provider_model="veo-3.1-lite-generate-preview",
            price_per_second_usd=0.05,
            budget_usd=0.19,
            shots=(_shot(image),),
        )


def test_veo_rest_payload_poll_and_download(tmp_path: Path) -> None:
    image_path = tmp_path / "source.jpg"
    Image.new("RGB", (16, 9), "white").save(image_path)
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert request.headers["x-goog-api-key"] == "secret"
        if request.method == "POST":
            body = json.loads(request.content)
            instance = body["instances"][0]
            assert instance["prompt"].startswith("Slow stable")
            assert "Avoid these failures: geometry drift" in instance["prompt"]
            assert base64.b64decode(instance["image"]["bytesBase64Encoded"])
            assert body["parameters"] == {
                "aspectRatio": "16:9",
                "durationSeconds": 4,
                "personGeneration": "allow_adult",
                "resolution": "720p",
                "seed": 42,
            }
            return httpx.Response(
                200,
                json={"name": "models/veo-3.1-lite-generate-preview/operations/video-1"},
            )
        if request.url.path.endswith("/operations/video-1"):
            return httpx.Response(
                200,
                json={
                    "name": "models/veo-3.1-lite-generate-preview/operations/video-1",
                    "done": True,
                    "response": {
                        "generateVideoResponse": {
                            "generatedSamples": [
                                {"video": {"uri": "https://download.test/video.mp4"}}
                            ]
                        }
                    },
                },
            )
        if request.url.host == "download.test":
            return httpx.Response(200, content=b"video", headers={"content-type": "video/mp4"})
        raise AssertionError(str(request.url))

    generation_input = VideoGenerationInput(
        shot_id="shot-01",
        source_image=image_path,
        prompt="Slow stable push.",
        negative_prompt="geometry drift",
        duration_seconds=4,
        aspect_ratio="16:9",
        resolution="720p",
        seed=42,
    )
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        provider = VeoVideoRenderer(_settings(), client=client, base_url="https://api.test/v1beta")
        started = provider.start(generation_input)
        assert started.name.endswith("operations/video-1")
        completed = provider.get(started.name)
        assert completed.done and completed.download_uri
        assert provider.download(completed) == b"video"
    assert len(calls) == 3
