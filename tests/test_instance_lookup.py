"""The instance pass has to name an object or refuse, never guess.

Before the lattice encoding, indices went into the low byte and the sRGB transfer crushed
neighbours together: a real render of 305 objects produced 4166 colours, 4.2% matched the manifest
and 60 manifest entries collided. A decoder built on that would have returned confident wrong
answers at every silhouette, which is worse than returning nothing.
"""

import json
from pathlib import Path

import pytest
from PIL import Image

from v365_archviz.application.instance_lookup import InstanceLookup


def _write_pass(directory: Path, colours: dict[tuple[int, int, int], str], size=(8, 4)) -> None:
    """Paint vertical stripes, one colour per object, left to right."""

    directory.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", size, (0, 0, 0))
    entries = []
    stripe = size[0] // max(1, len(colours))
    for index, (colour, role) in enumerate(colours.items(), start=1):
        for x in range(index * stripe - stripe, index * stripe):
            for y in range(size[1]):
                image.putpixel((x, y), colour)
        entries.append(
            {
                "instance_index": index,
                "object_name": f"obj-{index}",
                "semantic_role": role,
                "scene_element_id": None,
                "asset_instance_id": None,
                "asset_id": None,
                "encoded_rgb8": list(colour),
            }
        )
    image.save(directory / "instance_id.png")
    (directory / "instance_id_manifest.json").write_text(
        json.dumps({"schema_version": "1.0.0", "view_id": "view-01", "instances": entries}),
        encoding="utf-8",
    )


def test_a_pixel_resolves_to_its_object(tmp_path: Path) -> None:
    _write_pass(tmp_path, {(21, 0, 0): "main_shed", (0, 21, 0): "office_block"})
    lookup = InstanceLookup.load(tmp_path)

    left = lookup.at(1, 1)
    right = lookup.at(5, 1)

    assert left is not None and left.semantic_role == "main_shed"
    assert right is not None and right.semantic_role == "office_block"


def test_a_colour_between_two_objects_is_refused_rather_than_guessed(tmp_path: Path) -> None:
    """An edge blend belongs to neither object; naming it is how a selection lands on the wrong
    thing, so it has to come back as nothing."""

    _write_pass(tmp_path, {(42, 0, 0): "main_shed", (84, 0, 0): "office_block"})
    lookup = InstanceLookup.load(tmp_path)
    # Halfway between the two encoded colours, which is what antialiasing used to produce.
    lookup._pixels[0, 0] = [63, 0, 0]

    assert lookup.at(0, 0) is None


def test_a_region_answers_even_when_its_centre_pixel_is_an_edge(tmp_path: Path) -> None:
    _write_pass(tmp_path, {(42, 0, 0): "main_shed", (84, 0, 0): "office_block"})
    lookup = InstanceLookup.load(tmp_path)
    lookup._pixels[1, 1] = [63, 0, 0]

    dominant = lookup.dominant((0, 0, 4, 4))

    assert dominant is not None
    assert dominant.semantic_role == "main_shed"


def test_a_region_of_nothing_but_edges_returns_nothing(tmp_path: Path) -> None:
    _write_pass(tmp_path, {(42, 0, 0): "main_shed"})
    lookup = InstanceLookup.load(tmp_path)
    lookup._pixels[:, :] = [200, 200, 200]

    assert lookup.dominant((0, 0, 4, 4)) is None


def test_an_old_manifest_is_rejected_rather_than_silently_misread(tmp_path: Path) -> None:
    """The previous manifest recorded index bytes, not the bytes on disk. Reading it with this
    decoder would match almost nothing and report that as empty frames."""

    tmp_path.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (4, 4)).save(tmp_path / "instance_id.png")
    (tmp_path / "instance_id_manifest.json").write_text(
        json.dumps({"instances": [{"instance_index": 1, "srgb8": [1, 0, 0]}]}), encoding="utf-8"
    )

    with pytest.raises(ValueError, match="predates the lattice encoding"):
        InstanceLookup.load(tmp_path)


def test_an_incomplete_pass_is_an_error_not_an_empty_answer(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        InstanceLookup.load(tmp_path)


def test_coverage_and_decodable_share_agree_with_the_painted_stripes(tmp_path: Path) -> None:
    _write_pass(tmp_path, {(21, 0, 0): "main_shed", (0, 21, 0): "main_shed"})
    lookup = InstanceLookup.load(tmp_path)

    assert lookup.decodable_share() == pytest.approx(1.0)
    assert lookup.coverage()["main_shed"] == pytest.approx(1.0)
