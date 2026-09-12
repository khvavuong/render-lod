import json
from pathlib import Path

from PIL import Image

from v365_archviz.application.brand_deliverables import BrandDeliverables
from v365_archviz.application.brand_watermark import BrandWatermark


def test_branding_preserves_the_refined_composite_not_the_raw_provider_image(
    tmp_path: Path,
) -> None:
    generated = tmp_path / "generated"
    view = generated / "view-01"
    view.mkdir(parents=True)
    refined = view / "refined.png"
    provider = view / "provider_source.png"
    logo = tmp_path / "logo.png"
    Image.new("RGB", (100, 60), "red").save(refined)
    Image.new("RGB", (100, 60), "blue").save(provider)
    Image.new("RGBA", (8, 8), (255, 255, 255, 255)).save(logo)
    (view / "generation_manifest.json").write_text(json.dumps({"output": {}}), encoding="utf-8")

    result = BrandDeliverables().execute(
        BrandWatermark(
            logo_path=logo,
            opacity=0.5,
            width_ratio=0.1,
            margin_ratio=0.0,
        ),
        generated,
    )

    assert Image.open(view / "unbranded_refined.png").getpixel((50, 30)) == (255, 0, 0)
    assert Image.open(provider).getpixel((50, 30)) == (0, 0, 255)
    assert Image.open(refined).convert("RGB").getpixel((50, 30)) == (255, 0, 0)
    manifest = json.loads((view / "generation_manifest.json").read_text())
    assert manifest["output"]["brand_watermark"] is True
    assert result.image_paths == (refined,)
