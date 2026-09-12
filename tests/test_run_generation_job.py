from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from v365_archviz.application.run_generation_job import RunGenerationJob
from v365_archviz.config import Settings
from v365_archviz.domain.jobs import GenerationJob
from v365_archviz.domain.workflow import (
    Camera,
    GenerationProfile,
    ViewRole,
    ViewSet,
    WorkflowState,
)
from v365_archviz.providers.local_jobs import LocalJobRepository


def test_generation_stops_after_site_and_facade_masters_until_approval(
    tmp_path: Path,
    monkeypatch,  # type: ignore[no-untyped-def]
) -> None:
    settings = replace(Settings.from_env(), artifact_dir=tmp_path)
    repository = LocalJobRepository(tmp_path / "metadata")
    job = GenerationJob.create(
        job_id="job-master",
        idempotency_key="key-master",
        project_id="project",
        model_revision="model",
        design_revision="design",
        view_set_id="view-set",
        profile=GenerationProfile.MARKETING_HERO,
        initial_state=WorkflowState.GENERATING_VIEWSET,
    )
    repository.create_or_get(job)
    design_root = tmp_path / "scenes" / "model" / "designs" / "design"
    design_root.mkdir(parents=True)
    cameras = tuple(
        Camera(
            view_id=f"view-{index:02d}",
            role=role,
            position=(index, index, index),
            target=(0, 0, 0),
            focal_length_mm=35,
            sensor_width_mm=36,
            aspect_ratio="16:9",
        )
        for index, role in (
            (1, ViewRole.OVERALL),
            (2, ViewRole.DETAIL),
        )
    )
    (design_root / "view_set.json").write_text(
        ViewSet(
            view_set_id="view-set", design_revision="design", cameras=cameras
        ).model_dump_json(),
        encoding="utf-8",
    )
    (design_root / "design_dna.json").write_text("{}", encoding="utf-8")
    selected: list[tuple[str, ...]] = []
    approved_masters: list[Path | None] = []

    class RendererContext:
        def __enter__(self):  # type: ignore[no-untyped-def]
            return object()

        def __exit__(self, *_args):  # type: ignore[no-untyped-def]
            return None

    def refine(_self, _renderer, _render_root, generated_root, *_args, **kwargs):  # type: ignore[no-untyped-def]
        view_ids = kwargs["view_ids"]
        selected.append(view_ids)
        approved_masters.append(kwargs.get("approved_master_path"))
        view_root = generated_root / view_ids[0]
        view_root.mkdir(parents=True)
        Image.new("RGB", (16, 9), "white").save(view_root / "refined.jpg")
        manifest = generated_root / "viewset_generation_manifest.json"
        manifest.write_text("{}", encoding="utf-8")
        return SimpleNamespace(manifest_path=manifest)

    protected = tmp_path / "generated" / "model" / "design" / "protected_composite_manifest.json"
    monkeypatch.setattr(RunGenerationJob, "_ensure_conditioning", lambda *_args: None)
    monkeypatch.setattr(
        "v365_archviz.application.run_generation_job.build_refinement_prompt",
        lambda *_args: ({}, "prompt"),
    )
    monkeypatch.setattr(
        "v365_archviz.application.run_generation_job.select_master_view_ids",
        lambda *_args: ("view-01", "view-02"),
    )
    monkeypatch.setattr(
        "v365_archviz.application.run_generation_job.create_image_renderer",
        lambda *_args: RendererContext(),
    )
    monkeypatch.setattr("v365_archviz.application.run_generation_job.RefineViewSet.execute", refine)
    monkeypatch.setattr(
        "v365_archviz.application.run_generation_job.ProtectRefinement.execute",
        lambda *_args, **_kwargs: SimpleNamespace(rejected_count=0, manifest_path=protected),
    )

    result = RunGenerationJob().execute(job.job_id, settings)

    assert result.state is WorkflowState.DESIGN_MASTER_REVIEW
    assert selected == [("view-01",), ("view-02",)]
    assert approved_masters[0] is None
    assert approved_masters[1] == (
        tmp_path / "generated" / "model" / "design" / "view-01" / "refined.jpg"
    )
    review = __import__("json").loads(
        (tmp_path / "generated" / "model" / "design" / "design_master_review.json").read_text()
    )
    assert review["approved"] is False
    assert review["view_set_id"] == "view-set"
    assert review["master_view_ids"] == {"site": "view-01", "facade": "view-02"}
    assert review["quality_standard"]["role"] == "facade_quality_master"
    assert review["quality_standard"]["view_id"] == "view-02"


def test_technical_qa_failure_publishes_images_for_human_review(
    tmp_path: Path,
    monkeypatch,  # type: ignore[no-untyped-def]
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
