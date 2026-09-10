"""Durable generation job state and transition rules."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from v365_archviz.domain.common import DomainModel, utc_now
from v365_archviz.domain.workflow import GenerationProfile, WorkflowState

_ALLOWED_TRANSITIONS: dict[WorkflowState, frozenset[WorkflowState]] = {
    WorkflowState.RESOLVING_MODEL: frozenset(
        {WorkflowState.EXTRACTING_SCENE, WorkflowState.FAILED}
    ),
    WorkflowState.EXTRACTING_SCENE: frozenset(
        {WorkflowState.CLASSIFYING_SCENE, WorkflowState.FAILED}
    ),
    WorkflowState.CLASSIFYING_SCENE: frozenset(
        {WorkflowState.DESIGN_PLANNING, WorkflowState.NEEDS_INPUT, WorkflowState.FAILED}
    ),
    WorkflowState.DESIGN_PLANNING: frozenset(
        {WorkflowState.DESIGN_VALIDATION, WorkflowState.FAILED}
    ),
    WorkflowState.DESIGN_VALIDATION: frozenset(
        {WorkflowState.NEEDS_INPUT, WorkflowState.BUILDING_SCENE, WorkflowState.FAILED}
    ),
    WorkflowState.NEEDS_INPUT: frozenset({WorkflowState.DESIGN_PLANNING, WorkflowState.FAILED}),
    WorkflowState.BUILDING_SCENE: frozenset({WorkflowState.PLANNING_CAMERAS, WorkflowState.FAILED}),
    WorkflowState.PLANNING_CAMERAS: frozenset(
        {WorkflowState.RENDERING_PASSES, WorkflowState.FAILED}
    ),
    WorkflowState.RENDERING_PASSES: frozenset(
        {WorkflowState.GENERATING_VIEWSET, WorkflowState.FAILED}
    ),
    WorkflowState.GENERATING_VIEWSET: frozenset({WorkflowState.VALIDATING, WorkflowState.FAILED}),
    WorkflowState.VALIDATING: frozenset(
        {
            WorkflowState.REPAIRING,
            WorkflowState.HUMAN_REVIEW,
            WorkflowState.COMPOSING_BOARD,
            WorkflowState.FAILED,
        }
    ),
    WorkflowState.REPAIRING: frozenset(
        {WorkflowState.VALIDATING, WorkflowState.HUMAN_REVIEW, WorkflowState.FAILED}
    ),
    WorkflowState.HUMAN_REVIEW: frozenset(
        {WorkflowState.COMPOSING_BOARD, WorkflowState.REPAIRING, WorkflowState.FAILED}
    ),
    WorkflowState.COMPOSING_BOARD: frozenset(
        {WorkflowState.COMPLETED, WorkflowState.FAILED}
    ),
    WorkflowState.GENERATING_VIDEO: frozenset(
        {WorkflowState.COMPLETED, WorkflowState.FAILED}
    ),
    WorkflowState.COMPLETED: frozenset(),
    WorkflowState.FAILED: frozenset(),
}


class GenerationJob(DomainModel):
    job_id: str = Field(min_length=1)
    trace_id: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    model_revision: str = Field(min_length=1)
    design_revision: str = Field(min_length=1)
    view_set_id: str = Field(min_length=1)
    profile: GenerationProfile
    state: WorkflowState
    attempt: int = Field(default=0, ge=0)
    created_at: datetime
    updated_at: datetime
    artifact_refs: tuple[str, ...] = ()
    error_code: str | None = None
    error_message: str | None = None

    @classmethod
    def create(
        cls,
        *,
        job_id: str,
        idempotency_key: str,
        project_id: str,
        model_revision: str,
        design_revision: str,
        view_set_id: str,
        profile: GenerationProfile,
        initial_state: WorkflowState = WorkflowState.RESOLVING_MODEL,
    ) -> GenerationJob:
        now = utc_now()
        return cls(
            job_id=job_id,
            trace_id=f"trace-{idempotency_key[:16]}",
            idempotency_key=idempotency_key,
            project_id=project_id,
            model_revision=model_revision,
            design_revision=design_revision,
            view_set_id=view_set_id,
            profile=profile,
            state=initial_state,
            created_at=now,
            updated_at=now,
        )

    def transition(
        self,
        state: WorkflowState,
        *,
        artifact_refs: tuple[str, ...] | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> GenerationJob:
        if state not in _ALLOWED_TRANSITIONS[self.state]:
            raise ValueError(f"invalid workflow transition: {self.state.value} -> {state.value}")
        if state is WorkflowState.REPAIRING and self.attempt >= 3:
            raise ValueError("repair attempt limit reached; human review is required")
        return self.model_copy(
            update={
                "state": state,
                "updated_at": utc_now(),
                "attempt": self.attempt + (1 if state is WorkflowState.REPAIRING else 0),
                "artifact_refs": (
                    artifact_refs if artifact_refs is not None else self.artifact_refs
                ),
                "error_code": error_code,
                "error_message": error_message,
            }
        )
