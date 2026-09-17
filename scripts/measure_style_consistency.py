"""Measure how closely a generated view set kept the authored material palette.

A customer asking whether the system holds one design identity across layouts and across models
needs a number, not an impression. This reports, per view, how much of the image sits near each
authored palette role, and how far the image's own dominant colours drift from those roles.

Colour distance is CIE76 in Lab. It is the crude one, but it is the one whose thresholds people
quote: under about 2.3 a difference is not noticeable, and the comparison here is between runs
measured the same way, so the absolute scale matters less than whether two boards agree.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image


def _srgb_to_lab(rgb: tuple[int, int, int]) -> tuple[float, float, float]:
    def linear(channel: float) -> float:
        channel /= 255.0
        return channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4

    red, green, blue = (linear(float(value)) for value in rgb)
    x = (0.4124 * red + 0.3576 * green + 0.1805 * blue) / 0.95047
    y = 0.2126 * red + 0.7152 * green + 0.0722 * blue
    z = (0.0193 * red + 0.1192 * green + 0.9505 * blue) / 1.08883

    def f(value: float) -> float:
        return value ** (1 / 3) if value > 0.008856 else 7.787 * value + 16 / 116

    fx, fy, fz = f(x), f(y), f(z)
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def _delta_e(first: tuple[int, int, int], second: tuple[int, int, int]) -> float:
    a, b = _srgb_to_lab(first), _srgb_to_lab(second)
    return sum((x - y) ** 2 for x, y in zip(a, b, strict=True)) ** 0.5


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def _palette_roles(design_dna: Path) -> dict[str, tuple[int, int, int]]:
    palette = json.loads(design_dna.read_text(encoding="utf-8"))["material_palette"]
    return {
        role.removesuffix("_hex"): _hex_to_rgb(value)
        for role, value in palette.items()
        if role.endswith("_hex")
    }


def _measure(image_path: Path, roles: dict[str, tuple[int, int, int]], tolerance: float) -> dict:
    with Image.open(image_path) as handle:
        # Downsampling is the point, not a shortcut: it averages away compression noise and the
        # per-pixel texture the provider was asked to invent, leaving the colour fields.
        image = handle.convert("RGB").resize((256, 144), Image.Resampling.BOX)
    pixels = list(image.get_flattened_data())
    share = {role: 0 for role in roles}
    for pixel in pixels:
        nearest, distance = min(
            ((role, _delta_e(pixel, rgb)) for role, rgb in roles.items()),
            key=lambda item: item[1],
        )
        if distance <= tolerance:
            share[nearest] += 1
    total = len(pixels)
    return {role: round(count / total, 4) for role, count in share.items()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--board", action="append", required=True, metavar="LABEL=GENERATED_ROOT")
    parser.add_argument("--design-dna", action="append", required=True, metavar="LABEL=PATH")
    parser.add_argument("--tolerance", type=float, default=22.0)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()

    boards = dict(item.split("=", 1) for item in arguments.board)
    designs = dict(item.split("=", 1) for item in arguments.design_dna)
    report: dict[str, dict] = {}
    for label, root in boards.items():
        roles = _palette_roles(Path(designs[label]))
        views: dict[str, dict] = {}
        for view_dir in sorted(Path(root).glob("view-*")):
            candidates = sorted(view_dir.glob("unbranded_refined.*")) or sorted(
                view_dir.glob("refined.*")
            )
            if candidates:
                views[view_dir.name] = _measure(candidates[0], roles, arguments.tolerance)
        report[label] = {
            "palette": {
                role: "#{:02X}{:02X}{:02X}".format(*rgb) for role, rgb in roles.items()
            },
            "views": views,
            "board_mean": {
                role: round(sum(v[role] for v in views.values()) / len(views), 4)
                for role in roles
            }
            if views
            else {},
        }

    labels = list(report)
    roles = sorted(next(iter(report.values()))["palette"])
    print(f"{'role':12s} " + " ".join(f"{label:>10s}" for label in labels) + "   spread")
    for role in roles:
        values = [report[label]["board_mean"].get(role, 0.0) for label in labels]
        spread = max(values) - min(values)
        print(
            f"{role:12s} "
            + " ".join(f"{value:10.3f}" for value in values)
            + f"   {spread:6.3f}"
        )
    if arguments.output:
        arguments.output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"\nwritten to {arguments.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
