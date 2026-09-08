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
