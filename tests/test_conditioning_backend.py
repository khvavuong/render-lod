from pathlib import Path

import pytest

from v365_archviz.config import Settings
from v365_archviz.domain.workflow import RenderProfile
from v365_archviz.errors import ConfigurationError
from v365_archviz.providers.docker_conditioning import DockerConditioningRenderer
from v365_archviz.providers.local_blender_conditioning import (
    LocalBlenderConditioningRenderer,
    create_conditioning_renderer,
)


def test_docker_stays_the_default_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("V365_CONDITIONING_BACKEND", raising=False)
    settings = Settings.from_env()

    renderer = create_conditioning_renderer(settings.conditioning_backend)

    assert settings.conditioning_backend == "docker"
    assert type(renderer) is DockerConditioningRenderer


def test_local_backend_is_selected_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("V365_CONDITIONING_BACKEND", "local")

    renderer = create_conditioning_renderer(Settings.from_env().conditioning_backend)

    assert isinstance(renderer, LocalBlenderConditioningRenderer)


def test_unknown_backend_is_refused() -> None:
    with pytest.raises(ConfigurationError, match="unknown conditioning backend"):
        create_conditioning_renderer("podman")


def test_local_command_hands_blender_the_real_paths(tmp_path: Path) -> None:
    renderer = LocalBlenderConditioningRenderer(tmp_path, executable="blender-test")

    command = renderer._command(
        tmp_path / "scene.json",
        tmp_path / "design_dna.json",
        tmp_path / "view_set.json",
        tmp_path / "renders",
        RenderProfile.PREVIEW_FAST,
        tmp_path / "assets" / "manifest.json",
    )

    assert command[:4] == ["blender-test", "--background", "--python-exit-code", "1"]
    assert command[command.index("--python") + 1] == str(
        tmp_path / "scripts" / "blender" / "render_conditioning.py"
    )
    assert command[command.index("--scene") + 1] == str((tmp_path / "scene.json").resolve())
    assert command[command.index("--profile") + 1] == "preview_fast"
    assert not any(part.startswith("/workspace") for part in command)


def test_local_backend_refuses_when_blender_is_missing(tmp_path: Path) -> None:
    renderer = LocalBlenderConditioningRenderer(tmp_path, executable="no-such-blender-binary")

    with pytest.raises(ConfigurationError, match="Blender executable not found"):
        renderer._ensure_image()


def test_local_command_carries_the_facade_mode_and_scoring_profile(tmp_path: Path) -> None:
    """The seam must pass the new arguments, not just the old ones.

    `_command` is the only thing the local backend overrides. When the docker
    path inlined its command, this backend kept an override nothing called and
    quietly ran `docker run` from inside its own container.
    """

    renderer = LocalBlenderConditioningRenderer(tmp_path, executable="blender-test")

    command = renderer._command(
        tmp_path / "scene.json",
        tmp_path / "design_dna.json",
        tmp_path / "view_set.json",
        tmp_path / "renders",
        RenderProfile.PREVIEW_FAST,
        tmp_path / "assets" / "manifest.json",
        facade_mode="envelope_program",
        camera_scoring=True,
    )

    assert command[command.index("--facade-mode") + 1] == "envelope_program"
    assert command[command.index("--profile") + 1] == "camera_scoring"
    assert "docker" not in command


def test_the_docker_command_launches_the_checked_out_script(tmp_path: Path) -> None:
    renderer = DockerConditioningRenderer(tmp_path)

    command = renderer._command(
        tmp_path / "scene.json",
        tmp_path / "design_dna.json",
        tmp_path / "view_set.json",
        tmp_path / "renders",
        RenderProfile.PREVIEW_FAST,
        tmp_path / "assets" / "manifest.json",
        facade_mode="authored",
    )

    assert command[:3] == ["docker", "run", "--rm"]
    # The image runs blender over the mounted script rather than whatever an
    # older tag baked in.
    assert command[command.index("--entrypoint") + 1] == "blender"
    assert command[command.index("--python") + 1] == (
        "/workspace/scripts/blender/render_conditioning.py"
    )
    assert command[command.index("--facade-mode") + 1] == "authored"
