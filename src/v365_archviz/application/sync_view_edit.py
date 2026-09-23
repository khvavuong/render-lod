"""Carry one view's committed edit across to the other views of the set.

A view set is six cameras onto one building. Repainting a bush into view-03
leaves the two other cameras that can see that ground without it, and the set
stops describing one place. This is what puts the change into the rest of them.

It is a separate, asked-for step rather than part of every edit. An edit is one
provider call; a sync is one per remaining view, and plenty of edits — a smudge
on a wall only that camera sees — need no sync at all. Whoever is paying should
be the one who decides.

Each view keeps its own camera: its current image goes in as the authority for
composition, and the edited view goes in beside it as the authority for what
changed. Nothing is regenerated from the conditioning passes, so edits already
made to the other views survive.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from v365_archviz.application.apply_view_edit import (
    aspect_ratio_of,
    ensure_editable,
    requeue_for_validation,
    view_directory,
)
from v365_archviz.application.view_edit_store import (
    STATE_COMMITTED,
    ViewEditRecord,
    ViewEditStore,
)
from v365_archviz.config import Settings
from v365_archviz.domain.jobs import GenerationJob
from v365_archviz.errors import InvalidModelError, ProviderError
from v365_archviz.providers.contracts import ViewEditInput
from v365_archviz.providers.image_factory import ImageRenderer, create_image_renderer
from v365_archviz.providers.local_jobs import LocalJobRepository


@dataclass(frozen=True, slots=True)
class SyncedView:
    view_id: str
    record: ViewEditRecord | None
    error: str | None


@dataclass(frozen=True, slots=True)
class SyncedViewEdit:
    job: GenerationJob
    source_view_id: str
    views: tuple[SyncedView, ...]

    @property
    def changed(self) -> int:
        return sum(1 for view in self.views if view.record is not None)


def sync_prompt(original: str) -> str:
    """What the other views are asked for.

    The last sentence matters more than it looks: several of the six cameras
    cannot see the ground the edit touched, and without leave to do nothing they
    come back with the change invented somewhere it does not belong.
    """

    return (
        "Apply to this view the same change that was made to the reference image:\n\n"
        f"{original}\n\n"
        "Change only what that edit changed, and only where this view shows the same part "
        "of the site, at this view's own scale and angle. If this view does not show that "
        "part of the site, return the image unchanged."
    )


class SyncViewEdit:
    """Put one view's committed change into every other view of the set."""

    def execute(
        self,
        *,
        settings: Settings,
        repository: LocalJobRepository,
        job: GenerationJob,
        view_id: str,
        edit_id: str,
        created_by: str,
        on_view: Callable[[str, str], None] | None = None,
    ) -> SyncedViewEdit:
        ensure_editable(job)
        source_directory = view_directory(settings, job, view_id)
        source_store = ViewEditStore(source_directory)
        source = source_store.record(edit_id)
        if source.state != STATE_COMMITTED:
            raise InvalidModelError(
                f"edit {edit_id} has not been committed, so there is nothing to carry across"
            )
        master = source_store.current_image()
        targets = _sibling_views(source_directory)
        if not targets:
            raise InvalidModelError("this view set has no other view to synchronise")

        prompt = sync_prompt(source.prompt)
        renderer = create_image_renderer(settings, provider="openai-image")
        results: list[SyncedView] = []
        try:
            for directory in targets:
                other = directory.name
                if on_view is not None:
                    on_view(other, "running")
                try:
                    results.append(
                        self._one(
                            renderer=renderer,
                            directory=directory,
                            view_id=other,
                            master=master,
                            prompt=prompt,
                            source=source,
                            created_by=created_by,
                        )
                    )
                    if on_view is not None:
                        on_view(other, "done")
                except (ProviderError, InvalidModelError) as error:
                    # One camera failing is not a reason to leave the rest of the
                    # set half-synchronised and unreported.
                    results.append(SyncedView(view_id=other, record=None, error=str(error)))
                    if on_view is not None:
                        on_view(other, "failed")
        finally:
            close = getattr(renderer, "close", None)
            if callable(close):
                close()

        if all(view.record is None for view in results):
            raise ProviderError("no view could be synchronised; the set is unchanged")
        return SyncedViewEdit(
            job=requeue_for_validation(repository, job),
            source_view_id=view_id,
            views=tuple(results),
        )

    def _one(
        self,
        *,
        renderer: ImageRenderer,
        directory: Path,
        view_id: str,
        master: Path,
        prompt: str,
        source: ViewEditRecord,
        created_by: str,
    ) -> SyncedView:
        store = ViewEditStore(directory)
        current = store.current_image()
        produced = renderer.edit(
            ViewEditInput(
                view_id=view_id,
                base_image=current,
                prompt=prompt,
                mask=None,
                reference_images=(master,),
                reference_intent="change",
                aspect_ratio=aspect_ratio_of(current),
            )
        )
        record = store.open_record(
            edit_id=f"{source.edit_id}-{view_id}",
            view_id=view_id,
            kind="sync",
            prompt=prompt,
            candidates=tuple(image.content for image in produced),
            mask=None,
            request={
                "synced_from_view": source.view_id,
                "synced_from_edit": source.edit_id,
                "base_image": current.name,
            },
            created_by=created_by,
            provider_request_id=produced[0].provider_request_id if produced else None,
        )
        return SyncedView(
            view_id=view_id,
            record=store.commit_record(record, chosen=0),
            error=None,
        )


def _sibling_views(source: Path) -> tuple[Path, ...]:
    """Every other `view-*` directory of the same set, in their own order."""

    return tuple(
        path
        for path in sorted(source.parent.glob("view-*"))
        if path.is_dir() and path.name != source.name
    )
