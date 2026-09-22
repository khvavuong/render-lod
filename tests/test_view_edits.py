from __future__ import annotations

import base64
import io
import json
from dataclasses import replace
from pathlib import Path

import httpx
import pytest
from PIL import Image

from v365_archviz.application.apply_view_edit import ApplyViewEdit, CommitViewEdit
from v365_archviz.application.restore_view_edit import RestoreViewEdit
from v365_archviz.application.view_edit_store import ViewEditStore
from v365_archviz.config import Settings
from v365_archviz.domain.jobs import GenerationJob
from v365_archviz.domain.workflow import GenerationProfile, WorkflowState
from v365_archviz.errors import InvalidModelError
from v365_archviz.providers.contracts import GeneratedImage, ViewEditInput
from v365_archviz.providers.local_jobs import LocalJobRepository
from v365_archviz.providers.openai_image import OpenAIImageRenderer

VIEW_ID = "view-03"


def _png(size: tuple[int, int] = (32, 18), color: str = "white") -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, format="PNG")
    return buffer.getvalue()


def _mask(size: tuple[int, int] = (32, 18)) -> bytes:
    """Opaque black with a transparent hole, which is what the browser draws."""

    image = Image.new("RGBA", size, (0, 0, 0, 255))
    for x in range(4, 10):
        for y in range(4, 10):
            image.putpixel((x, y), (0, 0, 0, 0))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _settings(tmp_path: Path) -> Settings:
    return replace(Settings.from_env(), artifact_dir=tmp_path, openai_api_key="openai-secret")


def _job(state: WorkflowState = WorkflowState.HUMAN_REVIEW, attempt: int = 0) -> GenerationJob:
    job = GenerationJob.create(
        job_id="job-edit",
        idempotency_key="key-edit",
        project_id="project",
        model_revision="model",
        design_revision="design",
        view_set_id="view-set",
        profile=GenerationProfile.PREVIEW_FAST,
        initial_state=state,
    )
    return job.model_copy(update={"attempt": attempt})


def _view_dir(tmp_path: Path, *, extension: str = ".png") -> Path:
    directory = tmp_path / "generated" / "model" / "design" / VIEW_ID
    directory.mkdir(parents=True)
    (directory / f"refined{extension}").write_bytes(_png(color="red"))
    return directory


class _FakeRenderer:
    """A provider that records what it was asked and returns flat images."""

    capabilities = type("Caps", (), {"supports_masked_edit": True})()

    def __init__(self, count: int = 1) -> None:
        self.count = count
        self.requests: list[ViewEditInput] = []

    def edit(
        self,
        request: ViewEditInput,
        *,
        on_partial: object = None,
    ) -> tuple[GeneratedImage, ...]:
        self.requests.append(request)
        return tuple(
            GeneratedImage(
                content=_png(color="blue"),
                media_type="image/png",
                provider_request_id="req-1",
            )
            for _ in range(self.count)
        )

    def close(self) -> None:  # pragma: no cover - nothing to release
        pass


@pytest.fixture
def fake_renderer(monkeypatch: pytest.MonkeyPatch) -> _FakeRenderer:
    renderer = _FakeRenderer()

    def factory(*_: object, **__: object) -> _FakeRenderer:
        return renderer

    monkeypatch.setattr("v365_archviz.application.apply_view_edit.create_image_renderer", factory)
    return renderer


def _apply(
    tmp_path: Path,
    job: GenerationJob,
    *,
    candidates: int = 1,
    prompt: str = "làm sạch vệt bẩn trên tường",
) -> tuple[LocalJobRepository, object]:
    settings = _settings(tmp_path)
    repository = LocalJobRepository(tmp_path / "metadata")
    repository.create_or_get(job)
    applied = ApplyViewEdit().execute(
        settings=settings,
        repository=repository,
        job=job,
        view_id=VIEW_ID,
        edit_id="edit-1",
        prompt=prompt,
        mask=_mask(),
        candidates=candidates,
        created_by="nguoi-dung",
    )
    return repository, applied


def test_single_candidate_replaces_the_current_image_and_keeps_the_old_one(
    tmp_path: Path,
    fake_renderer: _FakeRenderer,
) -> None:
    directory = _view_dir(tmp_path)
    _, applied = _apply(tmp_path, _job())

    store = ViewEditStore(directory)
    assert store.current_image().read_bytes() == _png(color="blue")
    # Exactly one refined file, or every downstream consumer breaks.
    assert len(tuple(directory.glob("refined.*"))) == 1
    assert store.previous_image(applied.record).read_bytes() == _png(color="red")
    assert applied.record.state == "committed"
    assert applied.requeued is True


def test_the_edit_reopens_the_view_set_and_spends_one_repair_attempt(
    tmp_path: Path,
    fake_renderer: _FakeRenderer,
) -> None:
    _view_dir(tmp_path)
    repository, applied = _apply(tmp_path, _job(attempt=1))

    assert applied.job.state is WorkflowState.VALIDATING
    assert applied.job.attempt == 2
    assert repository.get("job-edit").state is WorkflowState.VALIDATING


def test_a_finished_view_set_can_still_be_edited(
    tmp_path: Path,
    fake_renderer: _FakeRenderer,
) -> None:
    _view_dir(tmp_path)
    _, applied = _apply(tmp_path, _job(state=WorkflowState.COMPLETED))

    assert applied.job.state is WorkflowState.VALIDATING


def test_a_jpeg_view_becomes_a_png_without_leaving_two_refined_files(
    tmp_path: Path,
    fake_renderer: _FakeRenderer,
) -> None:
    directory = _view_dir(tmp_path, extension=".jpg")
    _apply(tmp_path, _job())

    assert [path.name for path in directory.glob("refined.*")] == ["refined.png"]


def test_several_candidates_leave_the_view_untouched_until_one_is_chosen(
    tmp_path: Path,
    fake_renderer: _FakeRenderer,
) -> None:
    fake_renderer.count = 3
    directory = _view_dir(tmp_path)
    settings = _settings(tmp_path)
    repository, applied = _apply(tmp_path, _job(), candidates=3)

    assert applied.requeued is False
    assert applied.record.state == "pending"
    assert ViewEditStore(directory).current_image().read_bytes() == _png(color="red")

    committed = CommitViewEdit().execute(
        settings=settings,
        repository=repository,
        job=repository.get("job-edit"),
        view_id=VIEW_ID,
        edit_id="edit-1",
        chosen=2,
    )
    assert committed.record.chosen == 2
    assert ViewEditStore(directory).current_image().read_bytes() == _png(color="blue")
    assert committed.job.state is WorkflowState.VALIDATING


def test_restoring_appends_a_new_entry_rather_than_deleting_one(
    tmp_path: Path,
    fake_renderer: _FakeRenderer,
) -> None:
    directory = _view_dir(tmp_path)
    settings = _settings(tmp_path)
    repository, applied = _apply(tmp_path, _job())

    restored = RestoreViewEdit().execute(
        settings=settings,
        repository=repository,
        job=repository.get("job-edit"),
        view_id=VIEW_ID,
        source_edit_id=applied.record.edit_id,
        edit_id="edit-2",
        created_by="nguoi-dung",
    )
    store = ViewEditStore(directory)
    assert store.current_image().read_bytes() == _png(color="red")
    assert [record.edit_id for record in store.records()] == ["edit-1", "edit-2"]
    assert restored.record.kind == "restore"


def test_the_fourth_repair_is_refused(tmp_path: Path, fake_renderer: _FakeRenderer) -> None:
    _view_dir(tmp_path)
    with pytest.raises(InvalidModelError, match="three times"):
        _apply(tmp_path, _job(attempt=3))


def test_a_view_set_still_generating_has_nothing_to_edit(
    tmp_path: Path,
    fake_renderer: _FakeRenderer,
) -> None:
    _view_dir(tmp_path)
    with pytest.raises(InvalidModelError, match="no reviewable image"):
        _apply(tmp_path, _job(state=WorkflowState.RENDERING_PASSES))


def test_an_opaque_mask_is_refused_because_it_selects_nothing(
    tmp_path: Path,
    fake_renderer: _FakeRenderer,
) -> None:
    _view_dir(tmp_path)
    settings = _settings(tmp_path)
    repository = LocalJobRepository(tmp_path / "metadata")
    job = _job()
    repository.create_or_get(job)
    with pytest.raises(InvalidModelError, match="transparent pixels"):
        ApplyViewEdit().execute(
            settings=settings,
            repository=repository,
            job=job,
            view_id=VIEW_ID,
            edit_id="edit-1",
            prompt="đổi màu mái",
            mask=_png(),
            created_by="nguoi-dung",
        )


def test_an_empty_prompt_is_refused(tmp_path: Path, fake_renderer: _FakeRenderer) -> None:
    _view_dir(tmp_path)
    with pytest.raises(InvalidModelError, match="description"):
        _apply(tmp_path, _job(), prompt="   ")


def test_the_log_survives_a_reread(tmp_path: Path, fake_renderer: _FakeRenderer) -> None:
    directory = _view_dir(tmp_path)
    _apply(tmp_path, _job())

    manifest = json.loads((directory / "edits" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["edits"][0]["prompt"] == "làm sạch vệt bẩn trên tường"
    assert ViewEditStore(directory).record("edit-1").created_by == "nguoi-dung"


# -- provider ------------------------------------------------------------


def _openai_settings() -> Settings:
    return replace(Settings.from_env(), openai_api_key="openai-secret")


def test_the_edit_request_carries_the_mask_and_the_asked_quality(tmp_path: Path) -> None:
    base = tmp_path / "refined.png"
    base.write_bytes(_png())
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = request.content
        return httpx.Response(
            200,
            json={"data": [{"b64_json": base64.b64encode(_png()).decode("ascii")}]},
        )

    renderer = OpenAIImageRenderer(
        _openai_settings(),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    images = renderer.edit(
        ViewEditInput(
            view_id=VIEW_ID,
            base_image=base,
            prompt="đổi màu cửa",
            mask=_mask(),
            quality="max",
            size="1536x1024",
            aspect_ratio="16:9",
        )
    )
    body = bytes(seen["body"])  # type: ignore[arg-type]
    assert b'name="mask"' in body
    assert b'name="quality"\r\n\r\nmax' in body
    assert b'name="size"\r\n\r\n1536x1024' in body
    assert len(images) == 1


def test_a_streamed_edit_forwards_each_preview_then_the_finished_image(tmp_path: Path) -> None:
    base = tmp_path / "refined.png"
    base.write_bytes(_png())
    preview = base64.b64encode(_png(color="green")).decode("ascii")
    final = base64.b64encode(_png(color="blue")).decode("ascii")
    lines = (
        f'data: {{"type":"image_edit.partial_image","partial_image_index":0,'
        f'"b64_json":"{preview}"}}\n\n'
        f'data: {{"type":"image_edit.completed","b64_json":"{final}"}}\n\n'
        "data: [DONE]\n\n"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert b'name="stream"\r\n\r\ntrue' in request.content
        return httpx.Response(200, content=lines.encode("utf-8"))

    renderer = OpenAIImageRenderer(
        _openai_settings(),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    partials: list[int] = []
    images = renderer.edit(
        ViewEditInput(view_id=VIEW_ID, base_image=base, prompt="đổi màu cửa", mask=_mask()),
        on_partial=lambda index, _: partials.append(index),
    )
    assert partials == [0]
    assert len(images) == 1


def test_more_than_four_candidates_is_refused(tmp_path: Path) -> None:
    base = tmp_path / "refined.png"
    base.write_bytes(_png())
    renderer = OpenAIImageRenderer(
        _openai_settings(),
        client=httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200))),
    )
    with pytest.raises(Exception, match="one and four"):
        renderer.edit(
            ViewEditInput(view_id=VIEW_ID, base_image=base, prompt="x", candidates=5)
        )
