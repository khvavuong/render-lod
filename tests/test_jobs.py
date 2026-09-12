from pathlib import Path

import pytest

from v365_archviz.application.create_generation_job import CreateGenerationJob
from v365_archviz.domain.jobs import GenerationJob
from v365_archviz.domain.workflow import GenerationProfile, ViewSet, WorkflowState
from v365_archviz.providers.local_jobs import LocalJobRepository


def test_job_transition_rejects_skipping_required_stage() -> None:
    job = GenerationJob.create(
        job_id="job-1",
        idempotency_key="key-1",
        project_id="project",
        model_revision="model",
        design_revision="design",
        view_set_id="views",
        profile=GenerationProfile.PREVIEW_FAST,
    )

    with pytest.raises(ValueError, match="invalid workflow transition"):
        job.transition(WorkflowState.GENERATING_VIEWSET)


def test_image_job_completes_after_board_without_entering_video_flow() -> None:
    job = GenerationJob.create(
        job_id="job-images",
        idempotency_key="key-images",
        project_id="project",
        model_revision="model",
        design_revision="design",
        view_set_id="views",
        profile=GenerationProfile.MARKETING_HERO,
        initial_state=WorkflowState.COMPOSING_BOARD,
    )

    assert job.transition(WorkflowState.COMPLETED).state is WorkflowState.COMPLETED
    with pytest.raises(ValueError, match="invalid workflow transition"):
        job.transition(WorkflowState.GENERATING_VIDEO)


def test_failed_job_can_only_resume_from_explicit_safe_checkpoints() -> None:
    job = GenerationJob.create(
        job_id="job-retry",
        idempotency_key="key-retry",
        project_id="project",
        model_revision="model",
        design_revision="design",
        view_set_id="views",
        profile=GenerationProfile.MARKETING_HERO,
        initial_state=WorkflowState.VALIDATING,
    ).transition(WorkflowState.FAILED)

    assert job.transition(WorkflowState.VALIDATING).state is WorkflowState.VALIDATING
    with pytest.raises(ValueError, match="invalid workflow transition"):
        job.transition(WorkflowState.COMPOSING_BOARD)


def test_human_review_can_explicitly_reject_and_regenerate_viewset() -> None:
    job = GenerationJob.create(
        job_id="job-review-reject",
        idempotency_key="key-review-reject",
        project_id="project",
        model_revision="model",
        design_revision="design",
        view_set_id="views",
        profile=GenerationProfile.MARKETING_HERO,
        initial_state=WorkflowState.VALIDATING,
    ).transition(WorkflowState.HUMAN_REVIEW)

    regenerated = job.transition(WorkflowState.GENERATING_VIEWSET)
    assert regenerated.state is WorkflowState.GENERATING_VIEWSET


def test_repository_deduplicates_generation_job(tmp_path: Path) -> None:
    repository = LocalJobRepository(tmp_path / "metadata")
    view_set = ViewSet(
        view_set_id="views",
        design_revision="design",
        cameras=(),
    )
    use_case = CreateGenerationJob()

    first = use_case.execute(
        repository,
        project_id="project",
        model_revision="model",
        design_revision="design",
        view_set=view_set,
        profile=GenerationProfile.PREVIEW_FAST,
    )
    second = use_case.execute(
        repository,
        project_id="project",
        model_revision="model",
        design_revision="design",
        view_set=view_set,
        profile=GenerationProfile.PREVIEW_FAST,
    )

    assert first.created
    assert not second.created
    assert first.job == second.job
    assert repository.get_by_view_set("views") == first.job
    assert first.job.trace_id.startswith("trace-")


def test_image_provider_is_part_of_job_identity(tmp_path: Path) -> None:
    repository = LocalJobRepository(tmp_path / "metadata")
    view_set = ViewSet(view_set_id="views", design_revision="design", cameras=())
    use_case = CreateGenerationJob()

    gemini = use_case.execute(
        repository,
        project_id="project",
        model_revision="model",
        design_revision="design",
        view_set=view_set,
        profile=GenerationProfile.PREVIEW_FAST,
        image_provider="gemini",
    )
    openai = use_case.execute(
        repository,
        project_id="project",
        model_revision="model",
        design_revision="design",
        view_set=view_set,
        profile=GenerationProfile.PREVIEW_FAST,
        image_provider="openai-image",
    )

    assert gemini.created and openai.created
    assert gemini.job.job_id != openai.job.job_id
    assert openai.job.image_provider == "openai-image"


def test_repair_attempts_are_bounded() -> None:
    job = GenerationJob.create(
        job_id="job-1",
        idempotency_key="key-1",
        project_id="project",
        model_revision="model",
        design_revision="design",
        view_set_id="views",
        profile=GenerationProfile.PREVIEW_FAST,
        initial_state=WorkflowState.VALIDATING,
    )
    for attempt in range(3):
        job = job.transition(WorkflowState.REPAIRING)
        assert job.attempt == attempt + 1
        job = job.transition(WorkflowState.VALIDATING)

    with pytest.raises(ValueError, match="repair attempt limit"):
        job.transition(WorkflowState.REPAIRING)


def test_local_repository_rejects_unsafe_keys(tmp_path: Path) -> None:
    repository = LocalJobRepository(tmp_path / "metadata")

    with pytest.raises(ValueError, match="unsafe metadata storage key"):
        repository.get("../outside")
