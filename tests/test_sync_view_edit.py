from __future__ import annotations

import io
from dataclasses import replace
from pathlib import Path

import pytest
from PIL import Image

from v365_archviz.application.apply_view_edit import ApplyViewEdit
from v365_archviz.application.sync_view_edit import SyncViewEdit, sync_prompt
from v365_archviz.application.view_edit_store import ViewEditStore
from v365_archviz.config import Settings
from v365_archviz.domain.jobs import GenerationJob
from v365_archviz.domain.workflow import GenerationProfile, WorkflowState
from v365_archviz.errors import InvalidModelError, ProviderError
from v365_archviz.providers.contracts import GeneratedImage, ViewEditInput
from v365_archviz.providers.local_jobs import LocalJobRepository

SOURCE = "view-03"
VIEWS = ("view-01", "view-02", "view-03", "view-04")


def _png(color: str = "white") -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (32, 18), color).save(buffer, format="PNG")
    return buffer.getvalue()


def _mask() -> bytes:
    image = Image.new("RGBA", (32, 18), (0, 0, 0, 255))
    for x in range(4, 10):
        for y in range(4, 10):
            image.putpixel((x, y), (0, 0, 0, 0))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _settings(tmp_path: Path) -> Settings:
    return replace(Settings.from_env(), artifact_dir=tmp_path, openai_api_key="openai-secret")


def _job() -> GenerationJob:
    return GenerationJob.create(
        job_id="job-sync",
        idempotency_key="key-sync",
        project_id="project",
        model_revision="model",
        design_revision="design",
        view_set_id="view-set",
        profile=GenerationProfile.PREVIEW_FAST,
        initial_state=WorkflowState.HUMAN_REVIEW,
    )


def _view_set(tmp_path: Path) -> Path:
    root = tmp_path / "generated" / "model" / "design"
    for view in VIEWS:
        (root / view).mkdir(parents=True)
        (root / view / "refined.png").write_bytes(_png("red"))
    return root


class _FakeRenderer:
    capabilities = type("Caps", (), {"supports_masked_edit": True})()

    def __init__(self) -> None:
        self.requests: list[ViewEditInput] = []
        self.fail_on: set[str] = set()

    def edit(
        self,
        request: ViewEditInput,
        *,
        on_partial: object = None,
    ) -> tuple[GeneratedImage, ...]:
        self.requests.append(request)
        if request.view_id in self.fail_on:
            raise ProviderError(f"provider refused {request.view_id}")
        return (
            GeneratedImage(
                content=_png("blue"),
                media_type="image/png",
                provider_request_id="req-1",
            ),
        )

    def close(self) -> None:  # pragma: no cover - nothing to release
        pass


@pytest.fixture
def renderer(monkeypatch: pytest.MonkeyPatch) -> _FakeRenderer:
    fake = _FakeRenderer()
    for module in ("apply_view_edit", "sync_view_edit"):
        monkeypatch.setattr(
            f"v365_archviz.application.{module}.create_image_renderer",
            lambda *_, **__: fake,
        )
    return fake


def _edit(tmp_path: Path) -> tuple[LocalJobRepository, str]:
    settings = _settings(tmp_path)
    repository = LocalJobRepository(tmp_path / "metadata")
    job = _job()
    repository.create_or_get(job)
    applied = ApplyViewEdit().execute(
        settings=settings,
        repository=repository,
        job=job,
        view_id=SOURCE,
        edit_id="edit-1",
        prompt="thêm bụi cây xanh trước chân tường",
        mask=_mask(),
        created_by="nguoi-dung",
    )
    return repository, applied.record.edit_id


def _sync(tmp_path: Path, repository: LocalJobRepository, edit_id: str):
    return SyncViewEdit().execute(
        settings=_settings(tmp_path),
        repository=repository,
        job=repository.get("job-sync"),
        view_id=SOURCE,
        edit_id=edit_id,
        created_by="nguoi-dung",
    )


def test_every_other_view_gets_the_change(tmp_path: Path, renderer: _FakeRenderer) -> None:
    root = _view_set(tmp_path)
    repository, edit_id = _edit(tmp_path)

    synced = _sync(tmp_path, repository, edit_id)

    assert [view.view_id for view in synced.views] == ["view-01", "view-02", "view-04"]
    assert synced.changed == 3
    for view in ("view-01", "view-02", "view-04"):
        store = ViewEditStore(root / view)
        assert store.current_image().read_bytes() == _png("blue")
        assert store.records()[-1].kind == "sync"


def test_the_edited_view_is_left_alone(tmp_path: Path, renderer: _FakeRenderer) -> None:
    root = _view_set(tmp_path)
    repository, edit_id = _edit(tmp_path)

    _sync(tmp_path, repository, edit_id)

    # One entry, from the edit itself: syncing must not re-edit its own source.
    assert [r.kind for r in ViewEditStore(root / SOURCE).records()] == ["edit"]


def test_each_view_keeps_its_own_camera_and_is_told_what_changed(
    tmp_path: Path,
    renderer: _FakeRenderer,
) -> None:
    root = _view_set(tmp_path)
    repository, edit_id = _edit(tmp_path)

    _sync(tmp_path, repository, edit_id)

    for request in renderer.requests[1:]:
        # IMAGE 1 is the view's own current image, so its camera survives.
        assert request.base_image == root / request.view_id / "refined.png"
        # The edited view rides along as the authority for what changed.
        assert request.reference_images == (root / SOURCE / "refined.png",)
        assert request.reference_intent == "change"
        assert request.mask is None


def test_the_sync_prompt_lets_a_view_that_cannot_see_the_change_do_nothing() -> None:
    # Several of the six cameras do not show the ground an edit touched; without
    # leave to do nothing they invent the change somewhere it does not belong.
    text = sync_prompt("thêm bụi cây")
    assert "thêm bụi cây" in text
    assert "return the image unchanged" in text


def test_one_view_failing_does_not_abandon_the_rest(
    tmp_path: Path,
    renderer: _FakeRenderer,
) -> None:
    root = _view_set(tmp_path)
    repository, edit_id = _edit(tmp_path)
    renderer.fail_on = {"view-02"}

    synced = _sync(tmp_path, repository, edit_id)

    assert synced.changed == 2
    failed = next(view for view in synced.views if view.view_id == "view-02")
    assert failed.error is not None and "view-02" in failed.error
    assert ViewEditStore(root / "view-02").current_image().read_bytes() == _png("red")
    assert ViewEditStore(root / "view-04").current_image().read_bytes() == _png("blue")


def test_the_set_goes_back_through_the_gates_once(
    tmp_path: Path,
    renderer: _FakeRenderer,
) -> None:
    _view_set(tmp_path)
    repository, edit_id = _edit(tmp_path)
    before = repository.get("job-sync").attempt

    synced = _sync(tmp_path, repository, edit_id)

    assert synced.job.state is WorkflowState.VALIDATING
    assert synced.job.attempt == before + 1


def test_an_uncommitted_edit_has_nothing_to_carry_across(
    tmp_path: Path,
    renderer: _FakeRenderer,
) -> None:
    _view_set(tmp_path)
    settings = _settings(tmp_path)
    repository = LocalJobRepository(tmp_path / "metadata")
    job = _job()
    repository.create_or_get(job)
    ApplyViewEdit().execute(
        settings=settings,
        repository=repository,
        job=job,
        view_id=SOURCE,
        edit_id="edit-1",
        prompt="hai phương án",
        mask=_mask(),
        candidates=1,
        created_by="nguoi-dung",
    )
    with pytest.raises(InvalidModelError, match="no edit"):
        _sync(tmp_path, repository, "edit-khong-co")
