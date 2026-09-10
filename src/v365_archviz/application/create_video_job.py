"""Create an idempotent video job only after an explicit user request."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from v365_archviz.config import Settings
from v365_archviz.domain.jobs import GenerationJob
from v365_archviz.domain.video_jobs import VideoJob
from v365_archviz.providers.local_video_jobs import LocalVideoJobRepository


@dataclass(frozen=True, slots=True)
class CreatedVideoJob:
    job: VideoJob
    created: bool


class CreateVideoJob:
    def execute(
        self,
        repository: LocalVideoJobRepository,
        image_job: GenerationJob,
        settings: Settings,
        *,
        shot_count: int,
    ) -> CreatedVideoJob:
        if shot_count <= 0:
            raise ValueError("video job requires at least one shot")
        identity = "\n".join(
            (
                image_job.view_set_id,
                image_job.design_revision,
                settings.veo_model,
                settings.veo_resolution,
                str(settings.veo_duration_seconds),
            )
        )
        key = hashlib.sha256(identity.encode()).hexdigest()
        estimated_cost = round(
            shot_count * settings.veo_duration_seconds * settings.veo_price_per_second_usd, 4
        )
        candidate = VideoJob.create(
            video_job_id=f"video-job-{key[:16]}",
            idempotency_key=key,
            view_set_id=image_job.view_set_id,
            image_job_id=image_job.job_id,
            project_id=image_job.project_id,
            model_revision=image_job.model_revision,
            design_revision=image_job.design_revision,
            estimated_cost_usd=estimated_cost,
        )
        job, created = repository.create_or_get(candidate)
        return CreatedVideoJob(job=job, created=created)
