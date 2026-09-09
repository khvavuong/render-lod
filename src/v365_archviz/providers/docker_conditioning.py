"""Docker-backed renderer for deterministic geometry conditioning passes."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from v365_archviz.errors import ConfigurationError, ProviderError


class DockerConditioningRenderer:
    image = "v365-archviz-renderer:foundation"

    def __init__(self, workspace: Path | None = None) -> None:
        self._workspace = (workspace or Path.cwd()).resolve()

    def execute(
        self,
        scene_path: Path,
        design_dna_path: Path,
        view_set_path: Path,
        output_directory: Path,
    ) -> None:
        for path in (scene_path, design_dna_path, view_set_path):
            if not path.is_file():
                raise ProviderError(f"conditioning input not found: {path}")
        self._ensure_image()
        output_directory.mkdir(parents=True, exist_ok=True)
        command = [
            "docker",
            "run",
            "--rm",
            "--user",
            f"{os.getuid()}:{os.getgid()}",
            "-e",
            "HOME=/tmp",
            "-v",
            f"{self._workspace}:/workspace",
            self.image,
            "--scene",
            self._container_path(scene_path),
            "--design-dna",
            self._container_path(design_dna_path),
            "--view-set",
            self._container_path(view_set_path),
            "--output",
            self._container_path(output_directory),
        ]
        self._run(command, timeout=30 * 60, label="conditioning renderer")

    def _ensure_image(self) -> None:
        inspect = subprocess.run(
            ["docker", "image", "inspect", self.image],
            capture_output=True,
            text=True,
            check=False,
        )
        if inspect.returncode == 0:
            return
        dockerfile = self._workspace / "Dockerfile.renderer"
        if not dockerfile.is_file():
            raise ConfigurationError(f"renderer Dockerfile not found: {dockerfile}")
        self._run(
            [
                "docker",
                "build",
                "-f",
                str(dockerfile),
                "-t",
                self.image,
                str(self._workspace),
            ],
            timeout=30 * 60,
            label="renderer image build",
        )

    def _container_path(self, path: Path) -> str:
        resolved = path.resolve()
        try:
            relative = resolved.relative_to(self._workspace)
        except ValueError as exc:
            raise ConfigurationError(
                f"pipeline path must be inside workspace {self._workspace}: {resolved}"
            ) from exc
        return f"/workspace/{relative.as_posix()}"

    @staticmethod
    def _run(command: list[str], *, timeout: int, label: str) -> None:
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,
                timeout=timeout,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ProviderError(f"{label} could not run: {exc}") from exc
        if completed.returncode:
            detail = (completed.stderr or completed.stdout).strip()[-2000:]
            raise ProviderError(f"{label} failed: {detail}")
