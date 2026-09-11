from pathlib import Path

import pytest

from v365_archviz.application.create_video_job import CreateVideoJob
from v365_archviz.config import Settings
from v365_archviz.domain.jobs import GenerationJob
from v365_archviz.domain.video_jobs import VideoJobState
from v365_archviz.domain.workflow import GenerationProfile, WorkflowState
from v365_archviz.providers.local_video_jobs import LocalVideoJobRepository


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        environment="test",
        artifact_dir=tmp_path,
        log_level="INFO",
        gemini_api_key="secret",
        gemini_image_model="image-model",
        gemini_store_interactions=False,
        aps_client_id=None,
        aps_client_secret=None,
        aps_base_url="https://developer.api.autodesk.com",
        aps_region="US",
        aps_bucket_key=None,
    )


def _completed_image_job() -> GenerationJob:
    return GenerationJob.create(
        job_id="image-job",
        idempotency_key="image-key",
        project_id="project",
        model_revision="model",
        design_revision="design",
        view_set_id="views",
        profile=GenerationProfile.MARKETING_HERO,
        initial_state=WorkflowState.COMPLETED,
    )


def test_video_job_is_independent_and_idempotent(tmp_path: Path) -> None:
    repository = LocalVideoJobRepository(tmp_path / "metadata")
    use_case = CreateVideoJob()

    first = use_case.execute(repository, _completed_image_job(), _settings(tmp_path), shot_count=6)
    second = use_case.execute(repository, _completed_image_job(), _settings(tmp_path), shot_count=6)

    assert first.created is True
    assert second.created is False
    assert first.job == second.job
    assert first.job.state is VideoJobState.QUEUED
    assert first.job.estimated_cost_usd == 1.2


def test_video_job_has_its_own_transition_rules(tmp_path: Path) -> None:
    job = (
        CreateVideoJob()
        .execute(
            LocalVideoJobRepository(tmp_path / "metadata"),
            _completed_image_job(),
            _settings(tmp_path),
            shot_count=6,
        )
        .job
    )

    with pytest.raises(ValueError, match="invalid video transition"):
        job.transition(VideoJobState.GENERATING)

    assert job.transition(VideoJobState.PLANNING).state is VideoJobState.PLANNING
