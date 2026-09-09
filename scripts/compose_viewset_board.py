"""Compose a generic contact sheet for a generated multi-view result."""

from __future__ import annotations

import argparse
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from v365_archviz.application.brand_watermark import BrandWatermark


def _image_for(view_directory: Path, image_name: str | None = None) -> Path:
    if image_name:
        image = view_directory / image_name
        if not image.is_file():
            raise ValueError(f"expected {image_name} in {view_directory}")
        return image
    provider_sources = sorted(view_directory.glob("provider_source.*"))
    if len(provider_sources) == 1:
        return provider_sources[0]
    candidates = sorted(view_directory.glob("refined.*"))
    if len(candidates) != 1:
        raise ValueError(f"expected one refined image in {view_directory}")
    return candidates[0]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("generated_root", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--columns", type=int, default=2)
    parser.add_argument("--cell-width", type=int, default=768)
    parser.add_argument("--cell-height", type=int, default=432)
    parser.add_argument(
        "--image-name",
        help="use an exact image name in every view directory instead of refined.*",
    )
    args = parser.parse_args()
    if args.columns < 1:
        parser.error("--columns must be positive")

    view_directories = sorted(
        path
        for path in args.generated_root.iterdir()
        if path.is_dir() and path.name.startswith("view-")
    )
    if not view_directories:
        parser.error(f"no generated views found in {args.generated_root}")

    header_height = 44
    rows = math.ceil(len(view_directories) / args.columns)
    board = Image.new(
        "RGB",
        (args.columns * args.cell_width, rows * (args.cell_height + header_height)),
        "#16191d",
    )
    draw = ImageDraw.Draw(board)
    font = ImageFont.load_default(size=20)
    for index, view_directory in enumerate(view_directories):
        column = index % args.columns
        row = index // args.columns
        left = column * args.cell_width
        top = row * (args.cell_height + header_height)
        draw.text((left + 16, top + 12), view_directory.name.upper(), fill="white", font=font)
        with Image.open(_image_for(view_directory, args.image_name)) as source:
            image = ImageOps.fit(
                source.convert("RGB"),
                (args.cell_width, args.cell_height),
                method=Image.Resampling.LANCZOS,
            )
        board.paste(image, (left, top + header_height))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    source_output = args.output.with_name(f"unbranded_{args.output.name}")
    board.save(source_output, quality=92)
    BrandWatermark().apply_image(source_output, args.output)


if __name__ == "__main__":
    main()
