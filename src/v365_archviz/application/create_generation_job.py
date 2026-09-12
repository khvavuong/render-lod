"""Create one idempotent durable job for an immutable view set."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from v365_archviz.domain.jobs import GenerationJob
from v365_archviz.domain.workflow import GenerationProfile, RenderProfile, ViewSet, WorkflowState
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
    render_profile: RenderProfile,
    image_provider: str = "gemini",
    reference_hashes: tuple[str, ...] = (),
) -> str:
    payload = "\n".join(
        (
            project_id,
            model_revision,
            design_revision,
            view_set_id,
            profile.value,
            render_profile.value,
            image_provider,
            *reference_hashes,
        )
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
        render_profile: RenderProfile = RenderProfile.STANDARD_EEVEE,
        image_provider: str = "gemini",
        reference_image_refs: tuple[str, ...] = (),
        reference_roles: tuple[str, ...] = (),
    ) -> CreatedGenerationJob:
        key = generation_idempotency_key(
            project_id,
            model_revision,
            design_revision,
            view_set.view_set_id,
            profile,
            render_profile,
            image_provider,
            tuple(Path(value).parent.name for value in reference_image_refs),
        )
        candidate = GenerationJob.create(
            job_id=f"job-{key[:16]}",
            idempotency_key=key,
            project_id=project_id,
            model_revision=model_revision,
            design_revision=design_revision,
            view_set_id=view_set.view_set_id,
            profile=profile,
            render_profile=render_profile,
            image_provider=image_provider,
            reference_image_refs=reference_image_refs,
            reference_roles=reference_roles,
            initial_state=WorkflowState.PLANNING_CAMERAS,
        )
        job, created = repository.create_or_get(candidate)
        return CreatedGenerationJob(job=job, created=created)
