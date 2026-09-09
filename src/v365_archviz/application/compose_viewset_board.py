"""Compose the six generated views into one deterministic presentation board."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from v365_archviz.application.brand_watermark import BrandWatermark
from v365_archviz.errors import InvalidModelError


@dataclass(frozen=True, slots=True)
class ComposedBoard:
    board_path: Path
    view_count: int


def _image_for(view_directory: Path) -> Path:
    provider_sources = sorted(view_directory.glob("provider_source.*"))
    if len(provider_sources) == 1:
        return provider_sources[0]
    candidates = sorted(view_directory.glob("refined.*"))
    if len(candidates) != 1:
        raise InvalidModelError(f"expected one refined image in {view_directory}")
    return candidates[0]


class ComposeViewSetBoard:
    def execute(
        self,
        generated_root: Path,
        output_path: Path,
        *,
        columns: int = 2,
        cell_width: int = 768,
        cell_height: int = 432,
        watermark: BrandWatermark | None = None,
    ) -> ComposedBoard:
        if columns < 1:
            raise ValueError("columns must be positive")
        view_directories = sorted(
            path
            for path in generated_root.iterdir()
            if path.is_dir() and path.name.startswith("view-")
        )
        if not view_directories:
            raise InvalidModelError(f"no generated views found in {generated_root}")

        header_height = 44
        rows = math.ceil(len(view_directories) / columns)
        board = Image.new(
            "RGB",
            (columns * cell_width, rows * (cell_height + header_height)),
            "#16191d",
        )
        draw = ImageDraw.Draw(board)
        font = ImageFont.load_default(size=20)
        for index, view_directory in enumerate(view_directories):
            column = index % columns
            row = index // columns
            left = column * cell_width
            top = row * (cell_height + header_height)
            draw.text(
                (left + 16, top + 12),
                view_directory.name.upper(),
                fill="white",
                font=font,
            )
            with Image.open(_image_for(view_directory)) as source:
                image = ImageOps.fit(
                    source.convert("RGB"),
                    (cell_width, cell_height),
                    method=Image.Resampling.LANCZOS,
                )
            board.paste(image, (left, top + header_height))

        output_path.parent.mkdir(parents=True, exist_ok=True)
        if watermark is None:
            board.save(output_path, quality=92)
        else:
            source_path = output_path.with_name(f"unbranded_{output_path.name}")
            board.save(source_path, quality=92)
            watermark.apply_image(source_path, output_path)
        return ComposedBoard(output_path, len(view_directories))
