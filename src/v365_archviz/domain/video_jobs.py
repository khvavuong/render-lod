"""Durable state for an explicitly requested video-generation workflow."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import Field

from v365_archviz.domain.common import DomainModel, utc_now


class VideoJobState(str, Enum):
    QUEUED = "queued"
    PLANNING = "planning"
    GENERATING = "generating"
    ASSEMBLING = "assembling"
    COMPLETED = "completed"
    FAILED = "failed"


_ALLOWED_TRANSITIONS: dict[VideoJobState, frozenset[VideoJobState]] = {
    VideoJobState.QUEUED: frozenset({VideoJobState.PLANNING, VideoJobState.FAILED}),
    VideoJobState.PLANNING: frozenset({VideoJobState.GENERATING, VideoJobState.FAILED}),
    VideoJobState.GENERATING: frozenset({VideoJobState.ASSEMBLING, VideoJobState.FAILED}),
    VideoJobState.ASSEMBLING: frozenset({VideoJobState.COMPLETED, VideoJobState.FAILED}),
    VideoJobState.COMPLETED: frozenset(),
    VideoJobState.FAILED: frozenset(),
}


class VideoJob(DomainModel):
    video_job_id: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    view_set_id: str = Field(min_length=1)
    image_job_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    model_revision: str = Field(min_length=1)
    design_revision: str = Field(min_length=1)
    state: VideoJobState
    created_at: datetime
    updated_at: datetime
    estimated_cost_usd: float = Field(ge=0)
    artifact_refs: tuple[str, ...] = ()
    output_ref: str | None = None
    error_code: str | None = None
    error_message: str | None = None

    @classmethod
    def create(
        cls,
        *,
        video_job_id: str,
        idempotency_key: str,
        view_set_id: str,
        image_job_id: str,
        project_id: str,
        model_revision: str,
        design_revision: str,
        estimated_cost_usd: float,
    ) -> VideoJob:
        now = utc_now()
        return cls(
            video_job_id=video_job_id,
            idempotency_key=idempotency_key,
            view_set_id=view_set_id,
            image_job_id=image_job_id,
            project_id=project_id,
            model_revision=model_revision,
            design_revision=design_revision,
            state=VideoJobState.QUEUED,
            created_at=now,
            updated_at=now,
            estimated_cost_usd=estimated_cost_usd,
        )

    def transition(
        self,
        state: VideoJobState,
        *,
        artifact_refs: tuple[str, ...] | None = None,
        output_ref: str | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> VideoJob:
        if state not in _ALLOWED_TRANSITIONS[self.state]:
            raise ValueError(f"invalid video transition: {self.state.value} -> {state.value}")
        return self.model_copy(
            update={
                "state": state,
                "updated_at": utc_now(),
                "artifact_refs": artifact_refs or self.artifact_refs,
                "output_ref": output_ref if output_ref is not None else self.output_ref,
                "error_code": error_code,
                "error_message": error_message,
            }
        )
