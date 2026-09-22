"""Bring back the image an edit replaced, as one more step forward in the log."""

from __future__ import annotations

from v365_archviz.application.apply_view_edit import (
    AppliedViewEdit,
    requeue_for_validation,
    view_directory,
)
from v365_archviz.application.view_edit_store import ViewEditStore
from v365_archviz.config import Settings
from v365_archviz.domain.jobs import GenerationJob
from v365_archviz.errors import InvalidModelError
from v365_archviz.providers.local_jobs import LocalJobRepository


class RestoreViewEdit:
    """Undo by appending, never by erasing.

    Restoring the image from before edit 0002 writes a new entry 0003 whose own
    `previous` is what 0002 had produced. Nothing is lost, and a restore can
    itself be undone. The result goes back through QA like any other change,
    because the gates judge pixels, not intentions.
    """

    def execute(
        self,
        *,
        settings: Settings,
        repository: LocalJobRepository,
        job: GenerationJob,
        view_id: str,
        source_edit_id: str,
        edit_id: str,
        created_by: str,
    ) -> AppliedViewEdit:
        store = ViewEditStore(view_directory(settings, job, view_id))
        source = store.record(source_edit_id)
        if source.state != "committed":
            raise InvalidModelError(
                f"edit {source_edit_id} never replaced an image, so there is none to restore"
            )
        record = store.restore_record(source, edit_id=edit_id, created_by=created_by)
        return AppliedViewEdit(
            job=requeue_for_validation(repository, job),
            record=record,
            requeued=True,
        )
