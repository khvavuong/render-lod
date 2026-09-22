"""Repaint a masked region of one already refined view, then send it back through QA.

An edit is not a new picture beside the old one: it is the next version of the
view. So the result lands on the view's current image, the board and the
showreel are rebuilt from it, and the automated gates get to judge it exactly as
they judged the generated one. `ProtectRefinement` and `EvaluateConsistency` are
the reason a mask drawn across a building edge comes back rejected — that is the
system working, not failing.
"""

from __future__ import annotations

import io
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, UnidentifiedImageError

from v365_archviz.application.view_edit_store import ViewEditRecord, ViewEditStore
from v365_archviz.config import Settings
from v365_archviz.domain.jobs import GenerationJob
from v365_archviz.domain.workflow import WorkflowState
from v365_archviz.errors import InvalidModelError, ProviderError
from v365_archviz.providers.contracts import ViewEditInput
from v365_archviz.providers.image_factory import create_image_renderer
from v365_archviz.providers.local_jobs import LocalJobRepository

#: The states a person can be looking at a finished image in. Anything earlier
#: has no refined image to edit; FAILED has no image worth editing either.
EDITABLE_STATES = frozenset(
    {
        WorkflowState.VALIDATING,
        WorkflowState.HUMAN_REVIEW,
        WorkflowState.COMPLETED,
    }
)

MAX_REFERENCES = 16
MAX_CANDIDATES = 4


@dataclass(frozen=True, slots=True)
class AppliedViewEdit:
    job: GenerationJob
    record: ViewEditRecord
    requeued: bool


def view_directory(settings: Settings, job: GenerationJob, view_id: str) -> Path:
    directory = (
        settings.artifact_dir / "generated" / job.model_revision / job.design_revision / view_id
    )
    if not directory.is_dir():
        raise InvalidModelError(f"{view_id} has no generated output in this view set")
    return directory


def requeue_for_validation(
    repository: LocalJobRepository,
    job: GenerationJob,
) -> GenerationJob:
    """Reopen a judged view set so the gates run again over the changed pixels.

    Going through REPAIRING rather than straight to VALIDATING is deliberate:
    that is the transition `GenerationJob` counts, so a person editing by hand
    spends the same bounded budget an automatic repair would.
    """

    if job.state not in EDITABLE_STATES:
        raise InvalidModelError(
            f"a view set in state {job.state.value} has no reviewable image to edit"
        )
    repairing = job.transition(WorkflowState.REPAIRING)
    repository.save(repairing)
    validating = repairing.transition(WorkflowState.VALIDATING)
    repository.save(validating)
    return validating


def aspect_ratio_of(image_path: Path) -> str:
    """The view's own proportions, so an edit cannot quietly reframe the camera."""

    try:
        with Image.open(image_path) as image:
            width, height = image.size
    except (OSError, UnidentifiedImageError) as exc:
        raise InvalidModelError(f"current image is unreadable: {image_path}") from exc
    if width <= 0 or height <= 0:
        raise InvalidModelError(f"current image has no size: {image_path}")
    return f"{width}:{height}"


class ApplyViewEdit:
    """Ask the provider to repaint the mask, store what came back, decide nothing yet."""

    def execute(
        self,
        *,
        settings: Settings,
        repository: LocalJobRepository,
        job: GenerationJob,
        view_id: str,
        edit_id: str,
        prompt: str,
        mask: bytes | None,
        references: tuple[Path, ...] = (),
        quality: str | None = None,
        size: str | None = None,
        candidates: int = 1,
        created_by: str,
        on_partial: Callable[[int, bytes], None] | None = None,
    ) -> AppliedViewEdit:
        if not prompt.strip():
            raise InvalidModelError("an edit needs a description of what should change")
        if len(references) > MAX_REFERENCES:
            raise InvalidModelError(f"an edit takes at most {MAX_REFERENCES} reference images")
        if candidates < 1 or candidates > MAX_CANDIDATES:
            raise InvalidModelError(
                f"an edit produces between one and {MAX_CANDIDATES} candidates"
            )
        if job.state not in EDITABLE_STATES:
            raise InvalidModelError(
                f"a view set in state {job.state.value} has no reviewable image to edit"
            )
        if job.attempt >= 3:
            raise InvalidModelError(
                "this view set has already been repaired three times; it needs human review "
                "rather than another edit"
            )
        if mask is not None:
            _verify_mask(mask)

        store = ViewEditStore(view_directory(settings, job, view_id))
        current = store.current_image()
        renderer = create_image_renderer(settings, provider="openai-image")
        if not renderer.capabilities.supports_masked_edit:
            raise ProviderError("the configured image provider cannot repaint a masked region")
        try:
            produced = renderer.edit(
                ViewEditInput(
                    view_id=view_id,
                    base_image=current,
                    prompt=prompt,
                    mask=mask,
                    reference_images=references,
                    aspect_ratio=aspect_ratio_of(current),
                    quality=quality,
                    size=size,
                    candidates=candidates,
                ),
                on_partial=on_partial,
            )
        finally:
            close = getattr(renderer, "close", None)
            if callable(close):
                close()

        request: dict[str, Any] = {
            "view_set_id": job.view_set_id,
            "model_revision": job.model_revision,
            "design_revision": job.design_revision,
            "base_image": current.name,
            "quality": quality,
            "size": size,
            "reference_count": len(references),
            "masked": mask is not None,
        }
        record = store.open_record(
            edit_id=edit_id,
            view_id=view_id,
            kind="edit",
            prompt=prompt,
            candidates=tuple(image.content for image in produced),
            mask=mask,
            request=request,
            created_by=created_by,
            provider_request_id=produced[0].provider_request_id if produced else None,
        )
        # One candidate is one decision already made. Several are a question for
        # the person, so the view keeps its current image until they answer.
        if record.candidate_count == 1:
            record = store.commit_record(record, chosen=0)
            return AppliedViewEdit(
                job=requeue_for_validation(repository, job),
                record=record,
                requeued=True,
            )
        return AppliedViewEdit(job=job, record=record, requeued=False)


class CommitViewEdit:
    """Adopt one of several offered candidates as the view's image."""

    def execute(
        self,
        *,
        settings: Settings,
        repository: LocalJobRepository,
        job: GenerationJob,
        view_id: str,
        edit_id: str,
        chosen: int,
    ) -> AppliedViewEdit:
        store = ViewEditStore(view_directory(settings, job, view_id))
        record = store.commit_record(store.record(edit_id), chosen=chosen)
        return AppliedViewEdit(
            job=requeue_for_validation(repository, job),
            record=record,
            requeued=True,
        )


def _verify_mask(mask: bytes) -> None:
    """A mask without transparency selects nothing, and would silently repaint all."""

    try:
        with Image.open(io.BytesIO(mask)) as image:
            has_alpha = image.mode in {"LA", "RGBA", "PA"} or "transparency" in image.info
    except (OSError, UnidentifiedImageError) as exc:
        raise InvalidModelError("the mask is not a readable image") from exc
    if not has_alpha:
        raise InvalidModelError(
            "the mask must be a PNG whose transparent pixels mark the region to repaint"
        )
