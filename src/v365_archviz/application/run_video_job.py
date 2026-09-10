"""Run the explicitly requested video workflow independently from image generation."""

from __future__ import annotations

import logging
from pathlib import Path

from v365_archviz.application.assemble_video import AssembleVideo
from v365_archviz.application.brand_watermark import BrandWatermark
from v365_archviz.application.generate_video import GenerateVideoShots
from v365_archviz.application.plan_video import PlanVideo
from v365_archviz.config import Settings
from v365_archviz.domain.video_jobs import VideoJob, VideoJobState
from v365_archviz.providers.local_video_jobs import LocalVideoJobRepository
from v365_archviz.providers.veo import VeoVideoRenderer

logger = logging.getLogger(__name__)


class RunVideoJob:
    def execute(self, video_job_id: str, settings: Settings | None = None) -> VideoJob:
        resolved = settings or Settings.from_env()
        repository = LocalVideoJobRepository(resolved.artifact_dir / "metadata")
        job = repository.get(video_job_id)
        try:
            return self._run(repository, job, resolved)
        except Exception as exc:
            logger.exception("video job %s failed", video_job_id)
            current = repository.get(video_job_id)
            if current.state not in {VideoJobState.COMPLETED, VideoJobState.FAILED}:
                current = current.transition(
                    VideoJobState.FAILED,
                    error_code=type(exc).__name__,
                    error_message=(str(exc).strip() or type(exc).__name__)[-2000:],
                )
                repository.save(current)
            return current

    def _run(
        self,
        repository: LocalVideoJobRepository,
        job: VideoJob,
        settings: Settings,
    ) -> VideoJob:
        generated_root = (
            settings.artifact_dir / "generated" / job.model_revision / job.design_revision
        )
        view_set_path = (
            settings.artifact_dir
            / "scenes"
            / job.model_revision
            / "designs"
            / job.design_revision
            / "view_set.json"
        )

        if job.state is VideoJobState.QUEUED:
            job = self._advance(repository, job, VideoJobState.PLANNING)

        if job.state is VideoJobState.PLANNING:
            planned = PlanVideo().execute(
                generated_root,
                view_set_path,
                settings.artifact_dir / "videos",
                settings,
            )
            job = self._advance(
                repository, job, VideoJobState.GENERATING, planned.plan_path
            )

        if job.state is VideoJobState.GENERATING:
            plan_path = self._plan_path(job)
            video_root = plan_path.parent
            with VeoVideoRenderer(settings) as renderer:
                generated = GenerateVideoShots().execute(
                    renderer,
                    plan_path,
                    video_root,
                    poll_interval_seconds=settings.veo_poll_interval_seconds,
                    timeout_seconds=settings.veo_timeout_seconds,
                )
            job = self._advance(
                repository, job, VideoJobState.ASSEMBLING, generated.manifest_path
            )

        if job.state is VideoJobState.ASSEMBLING:
            plan_path = self._plan_path(job)
            video_root = plan_path.parent
            assembled = AssembleVideo().execute(
                plan_path,
                video_root,
                video_root / "showreel.mp4",
                watermark=BrandWatermark(),
            )
            refs = tuple(
                dict.fromkeys(
                    (*job.artifact_refs, str(assembled.report_path), str(assembled.video_path))
                )
            )
            job = job.transition(
                VideoJobState.COMPLETED,
                artifact_refs=refs,
                output_ref=str(assembled.video_path),
            )
            repository.save(job)
        return job

    @staticmethod
    def _advance(
        repository: LocalVideoJobRepository,
        job: VideoJob,
        state: VideoJobState,
        *paths: Path,
    ) -> VideoJob:
        refs = tuple(dict.fromkeys((*job.artifact_refs, *(str(path) for path in paths))))
        updated = job.transition(state, artifact_refs=refs)
        repository.save(updated)
        return updated

    @staticmethod
    def _plan_path(job: VideoJob) -> Path:
        matches = [Path(ref) for ref in job.artifact_refs if ref.endswith("video_plan.json")]
        if len(matches) != 1:
            raise RuntimeError("video job does not reference exactly one video plan")
        return matches[0]
