"""Create one idempotent durable job for an immutable view set."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from v365_archviz.domain.jobs import GenerationJob
from v365_archviz.domain.workflow import GenerationProfile, ViewSet, WorkflowState
from v365_archviz.providers.contracts import JobRepository


@dataclass(frozen=True, slots=True)
class CreatedGenerationJob:
    job: GenerationJob
    created: bool


def generation_idempotency_key(
    project_id: str,
    model_revision: str,
    design_revision: str,
    view_set_id: str,
    profile: GenerationProfile,
) -> str:
    payload = "\n".join(
        (project_id, model_revision, design_revision, view_set_id, profile.value)
    ).encode()
    return hashlib.sha256(payload).hexdigest()


class CreateGenerationJob:
    def execute(
        self,
        repository: JobRepository,
        *,
        project_id: str,
        model_revision: str,
        design_revision: str,
        view_set: ViewSet,
        profile: GenerationProfile,
    ) -> CreatedGenerationJob:
        key = generation_idempotency_key(
            project_id,
            model_revision,
            design_revision,
            view_set.view_set_id,
            profile,
        )
        candidate = GenerationJob.create(
            job_id=f"job-{key[:16]}",
            idempotency_key=key,
            project_id=project_id,
            model_revision=model_revision,
            design_revision=design_revision,
            view_set_id=view_set.view_set_id,
            profile=profile,
            initial_state=WorkflowState.PLANNING_CAMERAS,
        )
        job, created = repository.create_or_get(candidate)
        return CreatedGenerationJob(job=job, created=created)
