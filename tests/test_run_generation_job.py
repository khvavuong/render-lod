from pathlib import Path
from types import SimpleNamespace

from v365_archviz.application.run_generation_job import RunGenerationJob
from v365_archviz.config import Settings
from v365_archviz.domain.jobs import GenerationJob
from v365_archviz.domain.workflow import GenerationProfile, ViewSet, WorkflowState
from v365_archviz.providers.local_jobs import LocalJobRepository


def test_technical_qa_failure_publishes_images_for_human_review(
    tmp_path: Path, monkeypatch  # type: ignore[no-untyped-def]
) -> None:
    monkeypatch.setenv("V365_ARTIFACT_DIR", str(tmp_path))
    settings = Settings.from_env()
    repository = LocalJobRepository(tmp_path / "metadata")
    job = GenerationJob.create(
        job_id="job-review",
        idempotency_key="key-review",
        project_id="project",
        model_revision="model",
        design_revision="design",
        view_set_id="view-set",
        profile=GenerationProfile.MARKETING_HERO,
        initial_state=WorkflowState.VALIDATING,
    )
    repository.create_or_get(job)
    design_root = tmp_path / "scenes" / "model" / "designs" / "design"
    design_root.mkdir(parents=True)
    (design_root / "view_set.json").write_text(
        ViewSet(view_set_id="view-set", design_revision="design", cameras=()).model_dump_json(),
        encoding="utf-8",
    )
    generated_root = tmp_path / "generated" / "model" / "design"
    generated_root.mkdir(parents=True)
    technical = generated_root / "technical_qa.json"
    consistency = generated_root / "consistency_report.json"
    protected = generated_root / "protected_composite_manifest.json"
    protected.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(
        "v365_archviz.application.run_generation_job.ValidateGeneratedViewSet.execute",
        lambda *_args, **_kwargs: SimpleNamespace(
            passed=False, error_count=1, report_path=technical
        ),
    )
    monkeypatch.setattr(
        "v365_archviz.application.run_generation_job.EvaluateConsistency.execute",
        lambda *_args, **_kwargs: SimpleNamespace(report_path=consistency),
    )
    monkeypatch.setattr(
        "v365_archviz.application.run_generation_job.CreateCertificationReport.execute",
        lambda *_args, **_kwargs: None,
    )

    result = RunGenerationJob().execute(job.job_id, settings)

    assert result.state is WorkflowState.HUMAN_REVIEW
    assert result.error_code is None
    assert str(technical) in result.artifact_refs
