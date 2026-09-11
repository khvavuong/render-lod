"""Run the conditioning renderer with a Blender installed beside the control plane."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from v365_archviz.domain.workflow import RenderProfile
from v365_archviz.errors import ConfigurationError, ProviderError
from v365_archviz.providers.docker_conditioning import DockerConditioningRenderer

RENDER_SCRIPT = Path("scripts") / "blender" / "render_conditioning.py"


class LocalBlenderConditioningRenderer(DockerConditioningRenderer):
    """Same script, same arguments and same manifest, without a container of its own.

    Meant for an image that already carries Blender next to the API. From inside such
    a container the Docker backend would need the host's Docker socket, and the
    workspace it mounts is resolved on the host rather than in the container that
    asked, so the renderer would read a different directory from the one the API
    wrote.
    """

    image = "local-blender"

    def __init__(self, workspace: Path | None = None, executable: str | None = None) -> None:
        super().__init__(workspace)
        self._executable = executable or os.getenv("V365_BLENDER_EXECUTABLE") or "blender"

    def _ensure_image(self) -> None:
        if shutil.which(self._executable) is None:
            raise ConfigurationError(f"Blender executable not found: {self._executable}")
        script = self._workspace / RENDER_SCRIPT
        if not script.is_file():
            raise ConfigurationError(f"renderer script not found: {script}")

    def _image_id(self) -> str:
        completed = subprocess.run(
            [self._executable, "--version"],
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
        lines = (completed.stdout or "").strip().splitlines()
        if completed.returncode or not lines:
            raise ProviderError("Blender version could not be resolved")
        return lines[0].strip()

    def _command(
        self,
        scene_path: Path,
        design_dna_path: Path,
        view_set_path: Path,
        output_directory: Path,
        profile: RenderProfile,
        asset_library: Path,
    ) -> list[str]:
        return [
            self._executable,
            "--background",
            # Without it Blender exits 0 when the script raises, and a failed render
            # is only noticed later as missing passes.
            "--python-exit-code",
            "1",
            "--python",
            str(self._workspace / RENDER_SCRIPT),
            "--",
            "--scene",
            str(scene_path.resolve()),
            "--design-dna",
            str(design_dna_path.resolve()),
            "--view-set",
            str(view_set_path.resolve()),
            "--output",
            str(output_directory.resolve()),
            "--profile",
            profile.value,
            "--asset-library",
            str(asset_library.resolve()),
        ]


def create_conditioning_renderer(
    backend: str,
    workspace: Path | None = None,
) -> DockerConditioningRenderer:
    """Pick the renderer named by `V365_CONDITIONING_BACKEND`."""

    if backend == "docker":
        return DockerConditioningRenderer(workspace)
    if backend == "local":
        return LocalBlenderConditioningRenderer(workspace)
    raise ConfigurationError(
        f"unknown conditioning backend {backend!r}; expected 'docker' or 'local'"
    )
