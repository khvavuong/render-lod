"""Docker-backed renderer for deterministic geometry conditioning passes."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

from v365_archviz.artifacts import atomic_write
from v365_archviz.domain.controlled_realism import AssetLibraryManifest
from v365_archviz.domain.design import DesignDNA
from v365_archviz.domain.workflow import RenderProfile, ViewSet
from v365_archviz.errors import ConfigurationError, ProviderError


class DockerConditioningRenderer:
    image = "v365-archviz-renderer:layered-v1"

    def __init__(self, workspace: Path | None = None) -> None:
        self._workspace = (workspace or Path.cwd()).resolve()

    def execute(
        self,
        scene_path: Path,
        design_dna_path: Path,
        view_set_path: Path,
        output_directory: Path,
        profile: RenderProfile = RenderProfile.STANDARD_EEVEE,
        *,
        facade_mode: str = "authored",
        camera_scoring: bool = False,
        asset_library_path: Path | None = None,
    ) -> None:
        for path in (scene_path, design_dna_path, view_set_path):
            if not path.is_file():
                raise ProviderError(f"conditioning input not found: {path}")
        self._ensure_image()
        asset_library = asset_library_path or (
            self._workspace / "assets" / "pbr-v1" / "asset_library_manifest.json"
        )
        try:
            design = DesignDNA.model_validate_json(design_dna_path.read_text(encoding="utf-8"))
            library = AssetLibraryManifest.model_validate_json(
                asset_library.read_text(encoding="utf-8")
            )
        except (OSError, ValueError) as exc:
            raise ConfigurationError(f"invalid PBR asset library: {exc}") from exc
        self._validate_asset_files(asset_library, library)
        if library.library_version != design.asset_library_version:
            raise ConfigurationError(
                "Design DNA asset library version does not match renderer asset library"
            )
        output_directory.mkdir(parents=True, exist_ok=True)
        if facade_mode not in {"authored", "envelope_program", "envelope_only"}:
            raise ConfigurationError(f"unknown facade mode: {facade_mode}")
        command = self._command(
            scene_path,
            design_dna_path,
            view_set_path,
            output_directory,
            profile,
            asset_library,
            facade_mode=facade_mode,
            camera_scoring=camera_scoring,
        )
        self._run(command, timeout=30 * 60, label="conditioning renderer")
        try:
            view_set = ViewSet.model_validate_json(view_set_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ConfigurationError(f"invalid rendered view set: {exc}") from exc
        resolution = {
            RenderProfile.PREVIEW_FAST: (768, 432),
            RenderProfile.STANDARD_EEVEE: (1024, 576),
            RenderProfile.PREMIUM_CYCLES: (2048, 1152),
        }[profile]
        if camera_scoring:
            resolution = (512, 288)
        manifest = {
            "schema_version": "1.0.0",
            "view_set_id": view_set.view_set_id,
            "renderer_image": self.image,
            "renderer_image_id": self._image_id(),
            "render_profile": profile.value,
            "facade_mode": facade_mode,
            "renderer_script_sha256": hashlib.sha256(
                (self._workspace / "scripts/blender/render_conditioning.py").read_bytes()
            ).hexdigest(),
            "resolution": list(resolution),
            "scene_sha256": self._sha256(scene_path),
            "design_dna_sha256": self._sha256(design_dna_path),
            "view_set_sha256": self._sha256(view_set_path),
            "asset_library_version": library.library_version,
            "asset_library_sha256": self._sha256(asset_library),
            "view_ids": [camera.view_id for camera in view_set.cameras],
            "industrial_context": (
                design.industrial_context.model_dump(mode="json")
                if design.industrial_context is not None
                else None
            ),
        }
        if design.industrial_context is not None:
            context_content = (
                design.industrial_context.model_dump_json(indent=2).encode("utf-8") + b"\n"
            )
            atomic_write(output_directory / "industrial_context_plan.json", context_content)
            manifest["industrial_context_plan_sha256"] = hashlib.sha256(context_content).hexdigest()
        atomic_write(
            output_directory / "render_manifest.json",
            json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8") + b"\n",
        )

    def _command(
        self,
        scene_path: Path,
        design_dna_path: Path,
        view_set_path: Path,
        output_directory: Path,
        profile: RenderProfile,
        asset_library: Path,
        *,
        facade_mode: str = "authored",
        camera_scoring: bool = False,
    ) -> list[str]:
        """The docker invocation, kept a method so a backend can replace it.

        `LocalBlenderConditioningRenderer` overrides this and nothing else: the
        script, its arguments and the manifest are identical, only the way
        Blender is launched differs. Inlining this would silently give that
        backend a `docker run` to execute from inside its own container.

        `--entrypoint blender` runs the checked-out script rather than an older
        copy baked into an existing image tag.
        """

        uid_reader = getattr(os, "getuid", None)
        gid_reader = getattr(os, "getgid", None)
        return [
            "docker",
            "run",
            "--rm",
            *(["--gpus", "all"] if profile is RenderProfile.PREMIUM_CYCLES else []),
            *(["--user", f"{uid_reader()}:{gid_reader()}"] if uid_reader and gid_reader else []),
            "-e",
            "HOME=/tmp",
            "-v",
            f"{self._workspace}:/workspace",
            "--entrypoint",
            "blender",
            self.image,
            "--background",
            "--python",
            "/workspace/scripts/blender/render_conditioning.py",
            "--",
            "--facade-mode",
            facade_mode,
            "--scene",
            self._container_path(scene_path),
            "--design-dna",
            self._container_path(design_dna_path),
            "--view-set",
            self._container_path(view_set_path),
            "--output",
            self._container_path(output_directory),
            "--profile",
            "camera_scoring" if camera_scoring else profile.value,
            "--asset-library",
            self._container_path(asset_library),
        ]

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

    def _image_id(self) -> str:
        inspected = subprocess.run(
            ["docker", "image", "inspect", self.image, "--format", "{{.Id}}"],
            capture_output=True,
            text=True,
            check=False,
        )
        if inspected.returncode:
            raise ProviderError("renderer image identity could not be resolved")
        return inspected.stdout.strip()

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _validate_asset_files(
        self,
        manifest_path: Path,
        library: AssetLibraryManifest,
    ) -> None:
        root = manifest_path.resolve().parent
        for asset in library.assets:
            for item in asset.files:
                path = (root / item.path).resolve()
                try:
                    path.relative_to(root)
                except ValueError as exc:
                    raise ConfigurationError(
                        f"asset file escapes library root: {item.path}"
                    ) from exc
                if not path.is_file():
                    raise ConfigurationError(f"asset file not found: {path}")
                if self._sha256(path) != item.sha256:
                    raise ConfigurationError(f"asset checksum mismatch: {path}")

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
