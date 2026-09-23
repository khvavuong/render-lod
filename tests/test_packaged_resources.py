"""Everything under `resource/` that the service reads must be in the image.

The paths are resolved either from the package or from the working directory,
and both land on `/app/resource/...` in the container. `Dockerfile.local` only
copies the parts it names, so a new pack added to the source is invisible at
runtime until that COPY is added too — which is how a merge left the camera
planner asking for `resource/photography_packs/documentary_industrial.json` in
an image that had only `resource/logo`, and every view-set request answered 500.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPO_ROOT / "src"
DOCKERFILE = REPO_ROOT / "Dockerfile.local"

#: `resource/<this>/...` as written anywhere in the source.
_REFERENCE = re.compile(r"resource/([A-Za-z0-9_-]+)/")


def _referenced_directories() -> set[str]:
    found: set[str] = set()
    for path in SOURCE_ROOT.rglob("*.py"):
        found.update(_REFERENCE.findall(path.read_text(encoding="utf-8")))
    return found


def _copied_directories() -> set[str]:
    copied: set[str] = set()
    for line in DOCKERFILE.read_text(encoding="utf-8").splitlines():
        if line.startswith("COPY resource/"):
            copied.update(_REFERENCE.findall(line + "/"))
    return copied


def test_every_resource_the_source_reads_is_copied_into_the_image() -> None:
    missing = _referenced_directories() - _copied_directories()
    assert not missing, (
        f"the source reads resource/{sorted(missing)} but Dockerfile.local does not copy it; "
        "the container will raise FileNotFoundError at runtime"
    )


def test_the_named_resources_exist_in_the_repository() -> None:
    for directory in _referenced_directories():
        assert (REPO_ROOT / "resource" / directory).is_dir(), (
            f"resource/{directory} is read by the source but is not in the repository"
        )
