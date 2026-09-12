import io
import json
from pathlib import Path

from PIL import Image

from v365_archviz.application.brand_watermark import BrandWatermark
from v365_archviz.application.refine_view import (
    PROMPT_VERSION,
    RefineView,
)
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
    assert (tmp_path / "generated" / "view-01" / "unbranded_refined.png").is_file()
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


def test_uses_context_proxy_as_registered_conditioning_evidence(tmp_path: Path) -> None:
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
        assert image.convert("RGB").getpixel((0, 0)) == (0, 128, 0)
        assert image.convert("RGB").getpixel((1, 1)) == (0, 128, 0)
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["output"]["context_proxy_composited"] is False
    assert (
        manifest["input_roles"]["context_proxy_rgba"] == "camera_registered_conditioning_evidence"
    )


def test_regeneration_refreshes_unbranded_source_before_branding(tmp_path: Path) -> None:
    view = tmp_path / "renders" / "view-01"
    view.mkdir(parents=True)
    for name in ("base_rgb.png", "depth.png", "instance_id.png", "semantic.png", "edges.png"):
        Image.new("RGB", (2, 2), "white").save(view / name)
    target = tmp_path / "generated" / "view-01"
    target.mkdir(parents=True)
    Image.new("RGB", (2, 2), "red").save(target / "unbranded_refined.png")
    logo = tmp_path / "logo.png"
    Image.new("RGBA", (1, 1), (255, 255, 255, 255)).save(logo)

    RefineView().execute(
        FakeRenderer(),
        tmp_path / "renders",
        "view-01",
        tmp_path / "generated",
        watermark=BrandWatermark(
            logo_path=logo,
            opacity=0.5,
            width_ratio=0.1,
            margin_ratio=0.0,
        ),
    )

    with Image.open(target / "unbranded_refined.png") as source:
        assert source.convert("RGB").getpixel((1, 1)) == (0, 128, 0)
