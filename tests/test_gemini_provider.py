import base64
from dataclasses import replace
from pathlib import Path

import httpx
from PIL import Image

from v365_archviz.config import Settings
from v365_archviz.providers.contracts import (
    GeneratedImage,
    ViewConditioningInput,
    ViewSetGenerationInput,
)
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


def test_marketing_adapter_does_not_reinstate_strict_facade_or_translucent_context(tmp_path):
    image = tmp_path / "base.png"
    guide = tmp_path / "context_composition_guide.png"
    Image.new("RGB", (16, 9), "white").save(image)
    Image.new("RGB", (16, 9), "gray").save(guide)
    request = ViewConditioningInput(
        view_id="any-camera-slot",
        base_rgb=image,
        depth=image,
        instance_id=image,
        semantic=image,
        edges=image,
        structure_guide=image,
        prompt="Develop an industrial facade",
        role="hero",
        design_freedom="design_within_envelope",
        context_policy="resolve_proxies",
        reference_images=(guide,),
    )
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(500))) as client:
        renderer = GeminiImageRenderer(
            _settings(), client=client, conditioning_mode=GeminiConditioningMode.PHOTOREAL_BALANCED
        )
        blocks = renderer._photoreal_balanced_input(
            request, style_anchor=None, identity_prompt="Shared design"
        )
    labels = "\n".join(block["text"] for block in blocks if block["type"] == "text")
    assert "surfaces is massing study, not design" in labels
    assert "grounded, opaque, believable" in labels
    assert "reserved for deterministic post-composite" not in labels
    assert "neutral translucent mass" not in labels


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


def test_photoreal_balanced_uses_only_clean_authority_inputs(tmp_path: Path) -> None:
    image = tmp_path / "pass.png"
    reference = tmp_path / "reference.png"
    Image.new("RGB", (2, 2), "white").save(image)
    Image.new("RGB", (2, 2), "grey").save(reference)

    def handler(request: httpx.Request) -> httpx.Response:
        body = __import__("json").loads(request.content)
        assert body["response_format"] == {
            "type": "image",
            "aspect_ratio": "16:9",
            "image_size": "1K",
        }
        assert body["generation_config"] == {"thinking_level": "high"}
        assert len(body["input"]) == 11
        labels = [block["text"] for block in body["input"] if block["type"] == "text"]
        prompt = labels[0]
        assert "AUTHORITY" in prompt
        assert "PHOTOGRAPHIC DIRECTION" in prompt
        assert "COLOR ROLE CONTRACT — KEEP THE APPROVED PALETTE" in prompt
        assert "VIEW PURPOSE — TEST" in prompt
        assert any("BASE RGB" in label for label in labels)
        assert any("REALISM REFERENCE" in label for label in labels)
        assert any("MONOCHROME STRUCTURE AUTHORITY" in label for label in labels)
        assert any("AERIAL SITE-PLAN AUTHORITY" in label for label in labels)
        assert not any("DEPTH" in label for label in labels)
        assert not any("INSTANCE ID" in label for label in labels)
        assert not any("SEMANTIC ID" in label for label in labels)
        assert not any("STRUCTURAL EDGES" in label for label in labels)
        return httpx.Response(
            200,
            json={
                "id": "interaction-balanced",
                "output": {
                    "mime_type": "image/png",
                    "data": base64.b64encode(b"balanced-output").decode(),
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
        structure_guide=image,
        prompt=("COLOR ROLE CONTRACT — KEEP THE APPROVED PALETTE\n\nVIEW PURPOSE — TEST"),
        reference_images=(reference, image),
        role="overall",
    )
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        renderer = GeminiImageRenderer(
            _settings(),
            client=client,
            conditioning_mode=GeminiConditioningMode.PHOTOREAL_BALANCED,
        )
        result = renderer.generate(request_input)

    assert renderer.name == "gemini-photoreal_balanced"
    assert renderer.provenance["input_policy"] == (
        "base_rgb+structure_authority+design_master+two_role_references"
    )
    assert result.provider_request_id == "interaction-balanced"


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


def test_viewset_routes_every_view_to_the_quality_model(tmp_path: Path) -> None:
    image = tmp_path / "pass.png"
    Image.new("RGB", (2, 2), "white").save(image)
    models: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = __import__("json").loads(request.content)
        models.append(body["model"])
        return httpx.Response(
            200,
            json={
                "id": f"interaction-{len(models)}",
                "output": {
                    "mime_type": "image/png",
                    "data": base64.b64encode(f"output-{len(models)}".encode()).decode(),
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
            prompt="VIEW PURPOSE — TEST",
        )

    settings = replace(_settings(), gemini_master_image_model="gemini-3-pro-image")
    generation_request = ViewSetGenerationInput(
        request_id="generation-1",
        project_id="project-1",
        model_revision="model-1",
        design_revision="design-1",
        view_set_id="views-1",
        profile="marketing_hero",
        views=(view("view-01"), view("view-02")),
    )
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        renderer = GeminiImageRenderer(
            settings,
            client=client,
            conditioning_mode=GeminiConditioningMode.PHOTOREAL_BALANCED,
        )
        renderer.generate_view_set(generation_request)

    assert models == ["gemini-3-pro-image"] * 2


def test_tender_final_routes_every_view_to_the_quality_model(tmp_path: Path) -> None:
    image = tmp_path / "pass.png"
    Image.new("RGB", (2, 2), "white").save(image)
    models: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = __import__("json").loads(request.content)
        models.append(body["model"])
        return httpx.Response(
            200,
            json={
                "id": f"interaction-{len(models)}",
                "output": {
                    "mime_type": "image/png",
                    "data": base64.b64encode(f"output-{len(models)}".encode()).decode(),
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
            prompt="VIEW PURPOSE — TEST",
        )

    generation_request = ViewSetGenerationInput(
        request_id="generation-final",
        project_id="project-1",
        model_revision="model-1",
        design_revision="design-1",
        view_set_id="views-1",
        profile="tender_final",
        views=(view("view-01"), view("view-02"), view("view-03")),
    )
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        renderer = GeminiImageRenderer(
            replace(_settings(), gemini_master_image_model="gemini-3-pro-image"),
            client=client,
            conditioning_mode=GeminiConditioningMode.PHOTOREAL_BALANCED,
        )
        renderer.generate_view_set(generation_request)

    assert models == ["gemini-3-pro-image"] * 3


def test_single_design_master_uses_the_quality_model(tmp_path: Path) -> None:
    image = tmp_path / "pass.png"
    Image.new("RGB", (2, 2), "white").save(image)
    models: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = __import__("json").loads(request.content)
        models.append(body["model"])
        return httpx.Response(
            200,
            json={
                "id": "interaction-master",
                "output": {
                    "mime_type": "image/png",
                    "data": base64.b64encode(b"master-output").decode(),
                },
            },
        )

    master = ViewConditioningInput(
        view_id="view-04",
        base_rgb=image,
        depth=image,
        instance_id=image,
        semantic=image,
        edges=image,
        prompt="VIEW PURPOSE — DESIGN MASTER",
    )
    generation_request = ViewSetGenerationInput(
        request_id="generation-master",
        project_id="project-1",
        model_revision="model-1",
        design_revision="design-1",
        view_set_id="views-1",
        profile="marketing_hero",
        views=(master,),
        master_view_id="view-04",
    )
    settings = replace(_settings(), gemini_master_image_model="gemini-3-pro-image")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        GeminiImageRenderer(settings, client=client).generate_view_set(generation_request)

    assert models == ["gemini-3-pro-image"]


def test_preview_facade_master_with_site_anchor_still_uses_quality_model(
    tmp_path: Path,
) -> None:
    image = tmp_path / "pass.png"
    Image.new("RGB", (2, 2), "white").save(image)
    models: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = __import__("json").loads(request.content)
        models.append(body["model"])
        return httpx.Response(
            200,
            json={
                "id": "interaction-master",
                "output": {
                    "mime_type": "image/png",
                    "data": base64.b64encode(b"master-output").decode(),
                },
            },
        )

    master = ViewConditioningInput(
        view_id="view-03",
        base_rgb=image,
        depth=image,
        instance_id=image,
        semantic=image,
        edges=image,
        prompt="VIEW PURPOSE — FACADE MASTER",
    )
    generation_request = ViewSetGenerationInput(
        request_id="generation-preview-master",
        project_id="project-1",
        model_revision="model-1",
        design_revision="design-1",
        view_set_id="views-1",
        profile="preview_fast",
        views=(master,),
        master_view_id="view-02",
        design_master=GeneratedImage(b"site-master", "image/png", None),
    )
    settings = replace(_settings(), gemini_master_image_model="gemini-3-pro-image")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        GeminiImageRenderer(settings, client=client).generate_view_set(generation_request)

    assert models == ["gemini-3-pro-image"]


def test_viewset_reuses_an_external_approved_master(tmp_path: Path) -> None:
    image = tmp_path / "pass.png"
    Image.new("RGB", (2, 2), "white").save(image)
    calls: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = __import__("json").loads(request.content)
        calls.append(body)
        return httpx.Response(
            200,
            json={
                "id": f"interaction-{len(calls)}",
                "output": {
                    "mime_type": "image/png",
                    "data": base64.b64encode(f"output-{len(calls)}".encode()).decode(),
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
            prompt="VIEW PURPOSE — TEST",
        )

    approved = GeneratedImage(b"approved-master", "image/png", "master-request")
    generation_request = ViewSetGenerationInput(
        request_id="generation-1",
        project_id="project-1",
        model_revision="model-1",
        design_revision="design-1",
        view_set_id="views-1",
        profile="marketing_hero",
        views=(view("view-02"), view("view-03")),
        master_view_id="view-01",
        design_master=approved,
    )
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        renderer = GeminiImageRenderer(
            _settings(),
            client=client,
            conditioning_mode=GeminiConditioningMode.PHOTOREAL_BALANCED,
        )
        result = renderer.generate_view_set(generation_request)

    assert [view.view_id for view in result.views] == ["view-02", "view-03"]
    assert len(calls) == 2
    expected_master = base64.b64encode(b"approved-master").decode()
    assert all(call["input"][-1]["data"] == expected_master for call in calls)  # type: ignore[index]


def test_the_aerial_block_follows_the_role_not_the_view_id(tmp_path: Path) -> None:
    """Camera selection assigns slots by what a site can offer, so "view-01" is not always the
    overview. Keying the aerial site-plan block on the view id sent it to whatever happened to be
    first and withheld it from a real aerial that landed in another slot.
    """

    image = tmp_path / "pass.png"
    Image.new("RGB", (2, 2), "white").save(image)
    seen: list[list[str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = __import__("json").loads(request.content)
        seen.append([b["text"] for b in body["input"] if b["type"] == "text"])
        return httpx.Response(
            200,
            json={
                "id": "interaction",
                "output": {
                    "mime_type": "image/png",
                    "data": base64.b64encode(b"out").decode(),
                },
            },
        )

    def _request(view_id: str, role: str) -> ViewConditioningInput:
        return ViewConditioningInput(
            view_id=view_id,
            base_rgb=image,
            depth=image,
            instance_id=image,
            semantic=image,
            edges=image,
            prompt="Refine.",
            role=role,
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        renderer = GeminiImageRenderer(
            _settings(),
            client=client,
            conditioning_mode=GeminiConditioningMode.PHOTOREAL_BALANCED,
        )
        renderer.generate(_request("view-04", "overall"))
        renderer.generate(_request("view-01", "office_hero"))

    aerial_in_slot_four, facade_in_slot_one = seen
    assert any("AERIAL SITE-PLAN AUTHORITY" in label for label in aerial_in_slot_four)
    assert not any("AERIAL SITE-PLAN AUTHORITY" in label for label in facade_in_slot_one)


def test_the_structure_block_follows_the_granted_design_freedom(tmp_path: Path) -> None:
    """A pack granting design freedom used to arrive with a prompt saying the facade was the
    provider's to design and a conditioning block demanding the authored bay boundaries and exact
    opening count back. Both instructions were in the same request and cannot both be followed.
    """

    image = tmp_path / "pass.png"
    Image.new("RGB", (2, 2), "white").save(image)
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = __import__("json").loads(request.content)
        labels = [b["text"] for b in body["input"] if b["type"] == "text"]
        seen.append(next(label for label in labels if "STRUCTURE AUTHORITY" in label))
        return httpx.Response(
            200,
            json={
                "id": "interaction",
                "output": {
                    "mime_type": "image/png",
                    "data": base64.b64encode(b"out").decode(),
                },
            },
        )

    def _request(freedom: str) -> ViewConditioningInput:
        return ViewConditioningInput(
            view_id="view-05",
            base_rgb=image,
            depth=image,
            instance_id=image,
            semantic=image,
            edges=image,
            prompt="Refine.",
            structure_guide=image,
            role="office_hero",
            design_freedom=freedom,
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        renderer = GeminiImageRenderer(
            _settings(),
            client=client,
            conditioning_mode=GeminiConditioningMode.PHOTOREAL_BALANCED,
        )
        for freedom in ("photoreal_only", "detail_within_envelope", "design_within_envelope"):
            renderer.generate(_request(freedom))

    strict, detail, free = seen
    assert "exact authored/proposed opening count" in strict
    assert "exact authored/proposed opening count" not in detail
    assert "you may develop how each bay is" in detail
    assert "massing study, not design" in free
    # The envelope survives at every level, or the gates downstream have nothing to measure.
    for text in seen:
        assert "silhouette" in text


def test_the_base_render_stops_being_the_geometry_authority_when_design_is_freed(
    tmp_path: Path,
) -> None:
    """The structure-guide block was made freedom-aware, but three other places still labelled
    the base render the sole geometry authority on every request. The image block is the more
    concrete of the two instructions, so output kept reproducing the procedural fins even after
    design freedom became the default.
    """

    image = tmp_path / "pass.png"
    Image.new("RGB", (2, 2), "white").save(image)
    seen: list[list[str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = __import__("json").loads(request.content)
        seen.append([b["text"] for b in body["input"] if b["type"] == "text"])
        return httpx.Response(
            200,
            json={
                "id": "interaction",
                "output": {"mime_type": "image/png", "data": base64.b64encode(b"o").decode()},
            },
        )

    def _request(freedom: str) -> ViewConditioningInput:
        return ViewConditioningInput(
            view_id="view-01",
            base_rgb=image,
            depth=image,
            instance_id=image,
            semantic=image,
            edges=image,
            prompt="Refine.",
            role="office_hero",
            design_freedom=freedom,
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        renderer = GeminiImageRenderer(
            _settings(),
            client=client,
            conditioning_mode=GeminiConditioningMode.PHOTOREAL_BALANCED,
        )
        renderer.generate(_request("photoreal_only"))
        renderer.generate(_request("design_within_envelope"))

    strict, free = ("\n".join(labels) for labels in seen)
    assert "sole camera, geometry" in strict
    assert "sole camera, geometry" not in free
    assert "massing study, not design" in free
    # The camera never stops being authoritative, whatever the facade is allowed to become.
    for text in (strict, free):
        assert "camera" in text
