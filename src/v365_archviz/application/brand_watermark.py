"""Consistent, idempotent brand watermarking for raster and video deliverables."""

from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, UnidentifiedImageError

from v365_archviz.artifacts import atomic_write
from v365_archviz.errors import ConfigurationError, InvalidModelError, ProviderError

DEFAULT_LOGO_PATH = Path("resource/logo/logo_vertical.png")
DEFAULT_LOGO_OPACITY = 0.5
DEFAULT_LOGO_WIDTH_RATIO = 0.056
DEFAULT_LOGO_MARGIN_RATIO = 0.02


@dataclass(frozen=True, slots=True)
class BrandWatermark:
    """Apply one responsive top-left logo without modifying the source artifact."""

    logo_path: Path = DEFAULT_LOGO_PATH
    opacity: float = DEFAULT_LOGO_OPACITY
    width_ratio: float = DEFAULT_LOGO_WIDTH_RATIO
    margin_ratio: float = DEFAULT_LOGO_MARGIN_RATIO

    def __post_init__(self) -> None:
        if not self.logo_path.is_file():
            raise ConfigurationError(f"brand logo does not exist: {self.logo_path}")
        if not 0 < self.opacity <= 1:
            raise ConfigurationError("brand logo opacity must be in (0, 1]")
        if not 0 < self.width_ratio < 1:
            raise ConfigurationError("brand logo width ratio must be in (0, 1)")
        if not 0 <= self.margin_ratio < 0.5:
            raise ConfigurationError("brand logo margin ratio must be in [0, 0.5)")

    def _logo_for_width(self, frame_width: int) -> Image.Image:
        target_width = max(1, round(frame_width * self.width_ratio))
        try:
            with Image.open(self.logo_path) as source:
                logo = source.convert("RGBA")
        except (UnidentifiedImageError, OSError) as exc:
            raise InvalidModelError(
                f"brand logo is not a readable image: {self.logo_path}"
            ) from exc
        target_height = max(1, round(logo.height * target_width / logo.width))
        logo = logo.resize((target_width, target_height), Image.Resampling.LANCZOS)
        alpha = logo.getchannel("A").point(lambda value: round(value * self.opacity))
        logo.putalpha(alpha)
        return logo

    def apply_image(self, source_path: Path, output_path: Path) -> Path:
        if source_path.resolve() == output_path.resolve():
            raise InvalidModelError("watermark source and output image must differ")
        try:
            with Image.open(source_path) as source:
                frame = source.convert("RGBA")
                output_format = source.format
        except (UnidentifiedImageError, OSError) as exc:
            raise InvalidModelError(f"cannot watermark unreadable image: {source_path}") from exc
        logo = self._logo_for_width(frame.width)
        margin = round(frame.width * self.margin_ratio)
        frame.alpha_composite(logo, (margin, margin))

        suffix = output_path.suffix.lower()
        if suffix in {".jpg", ".jpeg"}:
            output_format = "JPEG"
            rendered = frame.convert("RGB")
            save_options: dict[str, Any] = {"quality": 95, "subsampling": 0}
        else:
            output_format = output_format if output_format in {"PNG", "WEBP"} else "PNG"
            rendered = frame
            save_options = {"optimize": True}
        buffer = io.BytesIO()
        rendered.save(buffer, format=output_format, **save_options)
        atomic_write(output_path, buffer.getvalue())
        return output_path

    def apply_video(self, source_path: Path, output_path: Path) -> Path:
        if source_path.resolve() == output_path.resolve():
            raise InvalidModelError("watermark source and output video must differ")
        ffmpeg = shutil.which("ffmpeg")
        ffprobe = shutil.which("ffprobe")
        if ffmpeg is None or ffprobe is None:
            raise ConfigurationError("ffmpeg and ffprobe are required for video watermarking")
        probe = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width",
                "-of",
                "json",
                str(source_path),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        try:
            body = json.loads(probe.stdout)
            streams = body["streams"]
            frame_width = int(streams[0]["width"])
        except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise InvalidModelError(f"cannot determine video dimensions: {source_path}") from exc
        logo_width = max(1, round(frame_width * self.width_ratio))
        margin = round(frame_width * self.margin_ratio)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            prefix=f".{output_path.stem}-",
            suffix=output_path.suffix or ".mp4",
            dir=output_path.parent,
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
        filter_graph = (
            f"[1:v]scale={logo_width}:-1,format=rgba,"
            f"colorchannelmixer=aa={self.opacity:.4f}[wm];"
            f"[0:v][wm]overlay={margin}:{margin}:format=auto[outv]"
        )
        command = [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(source_path),
            "-i",
            str(self.logo_path),
            "-filter_complex",
            filter_graph,
            "-map",
            "[outv]",
            "-map",
            "0:a?",
            "-c:v",
            "libx264",
            "-preset",
            "slow",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "copy",
            "-movflags",
            "+faststart",
            str(temporary_path),
        ]
        result = subprocess.run(command, check=False, capture_output=True, text=True)
        if result.returncode != 0:
            temporary_path.unlink(missing_ok=True)
            raise ProviderError(f"video watermarking failed: {result.stderr.strip()}")
        os.replace(temporary_path, output_path)
        return output_path
