from __future__ import annotations

from pathlib import Path

from PIL import Image

from v365_archviz.application.brand_watermark import BrandWatermark


def test_applies_responsive_half_opacity_logo_without_changing_source(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    output = tmp_path / "output.png"
    logo = tmp_path / "logo.png"
    Image.new("RGB", (100, 60), "white").save(source)
    Image.new("RGBA", (20, 10), (255, 0, 0, 255)).save(logo)

    watermark = BrandWatermark(
        logo_path=logo,
        opacity=0.5,
        width_ratio=0.2,
        margin_ratio=0.1,
    )
    watermark.apply_image(source, output)

    with Image.open(source) as original:
        assert original.getpixel((10, 10)) == (255, 255, 255)
    with Image.open(output).convert("RGB") as branded:
        red, green, blue = branded.getpixel((10, 10))
        assert red == 255
        assert green in {127, 128}
        assert blue in {127, 128}
        assert branded.getpixel((0, 0)) == (255, 255, 255)
