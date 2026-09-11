import io
import json
from pathlib import Path

from PIL import Image

from v365_archviz.application.refine_view import PROMPT_VERSION, RefineView
from v365_archviz.providers.contracts import GeneratedImage, ViewConditioningInput


class FakeRenderer:
    name = "fake"

    def generate(self, request: ViewConditioningInput) -> GeneratedImage:
        assert request.view_id == "view-01"
        buffer = io.BytesIO()
        Image.new("RGB", (2, 2), "green").save(buffer, format="PNG")
        return GeneratedImage(
            content=buffer.getvalue(),
            media_type="image/png",
            provider_request_id="request-1",
        )


def test_refines_complete_conditioning_pack_and_writes_manifest(tmp_path: Path) -> None:
    view = tmp_path / "renders" / "view-01"
    view.mkdir(parents=True)
    for name in (
        "base_rgb.png",
        "depth.png",
        "instance_id.png",
        "semantic.png",
        "edges.png",
    ):
        Image.new("RGB", (2, 2), "white").save(view / name)
    reference = tmp_path / "reference.jpg"
    Image.new("RGB", (2, 2), "blue").save(reference)

    result = RefineView().execute(
        FakeRenderer(),
        tmp_path / "renders",
        "view-01",
        tmp_path / "generated",
        reference_images=(reference,),
    )

    assert result.image_path.is_file()
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["provider"] == "fake"
    assert manifest["prompt_version"] == PROMPT_VERSION
    assert set(manifest["inputs"]) == {
        "base_rgb",
        "depth",
        "instance_id",
        "semantic",
        "edges",
        "reference_01",
    }


def test_composites_context_proxy_after_provider_output(tmp_path: Path) -> None:
    view = tmp_path / "renders" / "view-01"
    view.mkdir(parents=True)
    for name in ("base_rgb.png", "depth.png", "instance_id.png", "semantic.png", "edges.png"):
        Image.new("RGB", (2, 2), "white").save(view / name)
    overlay = Image.new("RGBA", (2, 2), (255, 0, 0, 0))
    overlay.putpixel((0, 0), (255, 0, 0, 255))
    overlay.save(view / "context_proxy_rgba.png")

    result = RefineView().execute(
        FakeRenderer(), tmp_path / "renders", "view-01", tmp_path / "generated"
    )

    with Image.open(result.image_path) as image:
        assert image.convert("RGB").getpixel((0, 0)) == (255, 0, 0)
        assert image.convert("RGB").getpixel((1, 1)) == (0, 128, 0)
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["output"]["context_proxy_composited"] is True
    assert manifest["input_roles"]["context_proxy_rgba"] == "deterministic_final_overlay"
