"""Resolve a pixel in the instance pass back to the object that produced it.

The pass used to be undecodable. Indices were written straight into the low byte, so two objects
differed by 1/255 before the sRGB transfer and by nothing after it; measured on a real render, 305
objects produced 4166 distinct colours, 4.2% of them matched the manifest and 60 manifest entries
collided outright. The renderer now spaces indices on a 13-level lattice and collapses the
reconstruction filter for ID passes, which brings the same scene to 683 colours, no collisions and
93.7% of pixels decodable.

This is the read side. It exists so that anything needing to know what is under a pixel — landmark
localisation for the camera lock, and later any selection a person makes on an image — asks one
place and gets an answer or an honest refusal, rather than a nearest colour that might be an edge
blend between two unrelated objects.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from numpy.typing import NDArray
from PIL import Image

#: Half the lattice spacing. A pixel further than this from every known colour is an edge blend
#: between objects, not an object: naming it would be a guess, so it is refused instead.
DEFAULT_TOLERANCE = 4


@dataclass(frozen=True, slots=True)
class InstanceRecord:
    instance_index: int
    object_name: str
    semantic_role: str
    scene_element_id: str | None
    asset_instance_id: str | None


@dataclass(frozen=True, slots=True)
class InstanceLookup:
    """A decoded instance pass, ready to answer questions about regions of the frame."""

    records: tuple[InstanceRecord, ...]
    _palette: NDArray[np.int16]
    _pixels: NDArray[np.int16]
    tolerance: int = DEFAULT_TOLERANCE

    @classmethod
    def load(
        cls,
        view_directory: Path,
        *,
        tolerance: int = DEFAULT_TOLERANCE,
    ) -> InstanceLookup:
        manifest_path = view_directory / "instance_id_manifest.json"
        image_path = view_directory / "instance_id.png"
        for path in (manifest_path, image_path):
            if not path.is_file():
                raise FileNotFoundError(f"instance pass is incomplete: {path}")
        document = json.loads(manifest_path.read_text(encoding="utf-8"))
        instances = document.get("instances")
        if not isinstance(instances, list) or not instances:
            raise ValueError(f"instance manifest carries no instances: {manifest_path}")
        if "encoded_rgb8" not in instances[0]:
            raise ValueError(
                "instance manifest predates the lattice encoding and records index bytes rather "
                f"than the bytes on disk; re-render this view: {manifest_path}"
            )
        records = tuple(
            InstanceRecord(
                instance_index=int(entry["instance_index"]),
                object_name=str(entry.get("object_name", "")),
                semantic_role=str(entry.get("semantic_role", "unknown")),
                scene_element_id=entry.get("scene_element_id"),
                asset_instance_id=entry.get("asset_instance_id"),
            )
            for entry in instances
        )
        palette = np.array([entry["encoded_rgb8"] for entry in instances], dtype=np.int16)
        with Image.open(image_path) as handle:
            pixels = np.asarray(handle.convert("RGB"), dtype=np.int16)
        return cls(records=records, _palette=palette, _pixels=pixels, tolerance=tolerance)

    @property
    def size(self) -> tuple[int, int]:
        return self._pixels.shape[1], self._pixels.shape[0]

    def _decode(self, samples: NDArray[np.int16]) -> NDArray[np.int64]:
        """Index into `records` per sample, or -1 where no colour is close enough."""

        distance = np.abs(samples[:, None, :] - self._palette[None, :, :]).max(axis=2)
        nearest = distance.argmin(axis=1)
        return np.where(distance.min(axis=1) <= self.tolerance, nearest, -1)

    def at(self, x: int, y: int) -> InstanceRecord | None:
        """The object at one pixel, or None when the pixel sits on an edge between objects."""

        width, height = self.size
        if not (0 <= x < width and 0 <= y < height):
            raise IndexError(f"pixel ({x}, {y}) is outside the {width}x{height} frame")
        index = int(self._decode(self._pixels[y, x][None, :])[0])
        return None if index < 0 else self.records[index]

    def dominant(self, box: tuple[int, int, int, int]) -> InstanceRecord | None:
        """The object covering most of a region, ignoring pixels that decode to nothing.

        A click or a comment lands on an area rather than a pixel, and the pixel under the cursor
        may be exactly the edge this decoder refuses to name. Asking the region keeps the answer
        stable without lowering the tolerance that makes refusals honest.
        """

        left, top, right, bottom = box
        width, height = self.size
        left, top = max(0, left), max(0, top)
        right, bottom = min(width, right), min(height, bottom)
        if right <= left or bottom <= top:
            raise ValueError(f"empty region: {box}")
        samples = self._pixels[top:bottom, left:right].reshape(-1, 3)
        decoded = self._decode(samples)
        decoded = decoded[decoded >= 0]
        if decoded.size == 0:
            return None
        counts = np.bincount(decoded, minlength=len(self.records))
        return self.records[int(counts.argmax())]

    def coverage(self) -> dict[str, float]:
        """Share of the frame each semantic role occupies, by decoded pixels."""

        samples = self._pixels.reshape(-1, 3)
        decoded = self._decode(samples)
        total = samples.shape[0]
        shares: dict[str, float] = {}
        for index in np.unique(decoded[decoded >= 0]):
            role = self.records[int(index)].semantic_role
            shares[role] = shares.get(role, 0.0) + float(np.count_nonzero(decoded == index)) / total
        return shares

    def decodable_share(self) -> float:
        """Fraction of the frame that names an object. The rest is edges between objects."""

        decoded = self._decode(self._pixels.reshape(-1, 3))
        return float(np.count_nonzero(decoded >= 0)) / decoded.size
