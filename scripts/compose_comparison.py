"""Compose a reproducible base-versus-refinement review board."""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("base", type=Path)
    parser.add_argument("refined", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    width, height = 688, 384
    header = 48
    board = Image.new("RGB", (width * 2, height + header), "white")
    draw = ImageDraw.Draw(board)
    font = ImageFont.load_default(size=18)
    for index, (path, label) in enumerate(
        ((args.base, "GEOMETRY BASE"), (args.refined, "GEMINI PREVIEW"))
    ):
        with Image.open(path) as source:
            image = source.convert("RGB")
            image.thumbnail((width, height))
            left = index * width + (width - image.width) // 2
            top = header + (height - image.height) // 2
            board.paste(image, (left, top))
        draw.text((index * width + 16, 14), label, fill="black", font=font)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    board.save(args.output, quality=92)


if __name__ == "__main__":
    main()
