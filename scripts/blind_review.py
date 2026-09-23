"""Lay out generated images for review without showing which configuration made them.

Every quality judgement in this project so far was made by someone who already knew which cell of
the experiment they were looking at, which is the condition under which people confirm what they
expected. This shuffles the images, strips the labels, writes the key to a separate file, and
emits a score sheet. The reviewer fills in the sheet; only then does the key get opened.

The rubric is the one the research plan specifies: composition, design plausibility, photographic
realism, material and lighting, source geometry retention, cross-view consistency.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
from pathlib import Path

from PIL import Image

RUBRIC = (
    ("composition", "Framing and the story the image tells"),
    ("design", "Industrial design and buildability plausibility"),
    ("realism", "Reads as a photograph rather than a render"),
    ("material_lighting", "Material response, light, asset scale"),
    ("geometry_retention", "Faithful to the source model's massing and layout"),
)


def _stable_shuffle(items: list[tuple[str, Path]], seed_source: str) -> list[tuple[str, Path]]:
    """Shuffle deterministically from a seed derived from the inputs.

    A fresh random order on every run would make two reviewers' sheets incomparable and would let
    anyone re-roll until the order suited them. Seeding from the entry list keeps the order fixed
    for a given experiment while still being unrelated to the configuration names.
    """

    seed = int(hashlib.sha256(seed_source.encode("utf-8")).hexdigest()[:16], 16)
    shuffled = list(items)
    random.Random(seed).shuffle(shuffled)
    return shuffled


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--entry",
        action="append",
        required=True,
        metavar="LABEL=IMAGE",
        help="one experiment cell; the label is hidden from the reviewer",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--width", type=int, default=1400)
    arguments = parser.parse_args()

    entries: list[tuple[str, Path]] = []
    for value in arguments.entry:
        label, _, path = value.partition("=")
        image = Path(path)
        if not image.is_file():
            raise SystemExit(f"image does not exist: {image}")
        entries.append((label, image))

    arguments.output.mkdir(parents=True, exist_ok=True)
    ordered = _stable_shuffle(entries, "|".join(sorted(label for label, _ in entries)))

    key: dict[str, str] = {}
    for position, (label, image) in enumerate(ordered, start=1):
        code = f"{position:02d}"
        with Image.open(image) as handle:
            frame = handle.convert("RGB")
            scale = arguments.width / frame.size[0]
            frame = frame.resize((arguments.width, round(frame.size[1] * scale)))
            frame.save(arguments.output / f"sample-{code}.jpg", quality=92)
        key[code] = label

    # The key lives beside the sheet but is opened only after scoring; keeping it out of the
    # image directory is what stops a reviewer glancing at it while they work.
    (arguments.output.parent / f"{arguments.output.name}_key.json").write_text(
        json.dumps(key, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    sheet = arguments.output / "score_sheet.csv"
    with sheet.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["sample", *(name for name, _ in RUBRIC), "notes"])
        for code in sorted(key):
            writer.writerow([f"sample-{code}", *("" for _ in RUBRIC), ""])

    print(f"{len(key)} samples written to {arguments.output}")
    print(f"key withheld at {arguments.output.parent / (arguments.output.name + '_key.json')}")
    print("\nrubric, score each 1-5:")
    for name, description in RUBRIC:
        print(f"  {name:20s} {description}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
