from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from v365_archviz.application.run_generation_job import RunGenerationJob
from v365_archviz.config import Settings
from v365_archviz.domain.jobs import GenerationJob
from v365_archviz.domain.style_pack import DesignFreedom, StylePack
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
        style_pack_snapshot=(
            StylePack.load(
                Path(__file__).resolve().parents[1]
                / "resource/style_packs/marketing_photoreal.json"
            ).to_json()
        ),
        reference_image_refs=(str(tmp_path / "factory-reference.jpg"),),
        reference_roles=("factory_design_reference",),
        initial_state=WorkflowState.GENERATING_VIEWSET,
    )
    Image.new("RGB", (16, 9), "gray").save(tmp_path / "factory-reference.jpg")
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
    references_by_call: list[tuple[Path, ...]] = []

    class RendererContext:
        def __enter__(self):  # type: ignore[no-untyped-def]
            return object()

        def __exit__(self, *_args):  # type: ignore[no-untyped-def]
            return None

    def refine(_self, _renderer, _render_root, generated_root, *_args, **kwargs):  # type: ignore[no-untyped-def]
        assert kwargs["style_pack"].design_freedom is DesignFreedom.DESIGN_WITHIN_ENVELOPE
        assert kwargs["attach_context_guide"] is True
        view_ids = kwargs["view_ids"]
        selected.append(view_ids)
        approved_masters.append(kwargs.get("approved_master_path"))
        references_by_call.append(kwargs.get("reference_images", ()))
        view_root = generated_root / view_ids[0]
        view_root.mkdir(parents=True)
        Image.new("RGB", (16, 9), "white").save(view_root / "refined.jpg")
        manifest = generated_root / "viewset_generation_manifest.json"
        manifest.write_text("{}", encoding="utf-8")
        return SimpleNamespace(manifest_path=manifest)

    protected = tmp_path / "generated" / "model" / "design" / "protected_composite_manifest.json"
    # Skips the Blender render but keeps the plan: the real method returns the
    # view set it rendered through, which is not always the one it was given.
    monkeypatch.setattr(RunGenerationJob, "_ensure_conditioning", lambda *args: args[2])
    monkeypatch.setattr(
        "v365_archviz.application.run_generation_job.build_refinement_prompt",
        lambda *_args, **kwargs: ({}, "prompt"),
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
    assert references_by_call == [(), (tmp_path / "factory-reference.jpg",)]
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


def test_targeted_repair_regenerates_only_requested_view_and_records_lineage(
    tmp_path: Path,
    monkeypatch,  # type: ignore[no-untyped-def]
) -> None:
    settings = replace(Settings.from_env(), artifact_dir=tmp_path)
    repository = LocalJobRepository(tmp_path / "metadata")
    job = (
        GenerationJob.create(
            job_id="job-targeted-repair",
            idempotency_key="key-targeted-repair",
            project_id="project",
            model_revision="model",
            design_revision="design",
            view_set_id="view-set",
            profile=GenerationProfile.TENDER_FINAL,
            initial_state=WorkflowState.VALIDATING,
        )
        .transition(WorkflowState.HUMAN_REVIEW)
        .transition(WorkflowState.REPAIRING)
    )
    repository.create_or_get(job)
    design_root = tmp_path / "scenes" / "model" / "designs" / "design"
    design_root.mkdir(parents=True)
    (design_root / "view_set.json").write_text(
        ViewSet(
            view_set_id="view-set",
            design_revision="design",
            cameras=(
                Camera(
                    view_id="view-03",
                    role=ViewRole.HERO,
                    position=(0, 0, 10),
                    target=(0, 1, 2),
                    focal_length_mm=35,
                    sensor_width_mm=36,
                    aspect_ratio="16:9",
                ),
            ),
        ).model_dump_json(),
        encoding="utf-8",
    )
    (design_root / "design_dna.json").write_text("{}", encoding="utf-8")
    generated = tmp_path / "generated" / "model" / "design"
    view = generated / "view-03"
    view.mkdir(parents=True)
    Image.new("RGB", (16, 9), "gray").save(view / "refined.jpg")
    site_master = generated / "site.jpg"
    facade_master = generated / "facade.jpg"
    Image.new("RGB", (16, 9), "white").save(site_master)
    Image.new("RGB", (16, 9), "white").save(facade_master)
    (generated / "design_master_review.json").write_text(
        __import__("json").dumps(
            {
                "approved": True,
                "master_view_ids": {"site": "view-01", "facade": "view-05"},
                "master_image_refs": {
                    "site": str(site_master),
                    "facade": str(facade_master),
                },
            }
        ),
        encoding="utf-8",
    )
    (generated / "manual_repair_request.json").write_text(
        '{"view_id":"view-03","instruction":"Improve only asphalt texture."}',
        encoding="utf-8",
    )
    generated_manifest = generated / "viewset_generation_manifest.json"
    protected = generated / "protected_composite_manifest.json"
    technical = generated / "technical_qa.json"
    consistency = generated / "consistency_report.json"
    certification = generated / "certification_report.json"
    selected: list[tuple[str, ...]] = []

    class RendererContext:
        def __enter__(self):  # type: ignore[no-untyped-def]
            return object()

        def __exit__(self, *_args):  # type: ignore[no-untyped-def]
            return None

    def refine(_self, _renderer, _render_root, generated_root, *_args, **kwargs):  # type: ignore[no-untyped-def]
        selected.append(kwargs["view_ids"])
        Image.new("RGB", (16, 9), "silver").save(generated_root / "view-03" / "refined.jpg")
        generated_manifest.write_text("{}", encoding="utf-8")
        return SimpleNamespace(manifest_path=generated_manifest)

    monkeypatch.setattr(
        "v365_archviz.application.run_generation_job.build_refinement_prompt",
        lambda *_args, **kwargs: ({}, "prompt"),
    )
    monkeypatch.setattr(
        "v365_archviz.application.run_generation_job.create_image_renderer",
        lambda *_args: RendererContext(),
    )
    monkeypatch.setattr("v365_archviz.application.run_generation_job.RefineViewSet.execute", refine)
    monkeypatch.setattr(
        "v365_archviz.application.run_generation_job.ProtectRefinement.execute",
        lambda *_args, **_kwargs: SimpleNamespace(manifest_path=protected),
    )
    monkeypatch.setattr(
        "v365_archviz.application.run_generation_job.ValidateGeneratedViewSet.execute",
        lambda *_args, **_kwargs: SimpleNamespace(report_path=technical),
    )
    monkeypatch.setattr(
        "v365_archviz.application.run_generation_job.EvaluateConsistency.execute",
        lambda *_args, **_kwargs: SimpleNamespace(report_path=consistency),
    )
    monkeypatch.setattr(
        "v365_archviz.application.run_generation_job.CreateCertificationReport.execute",
        lambda *_args, **_kwargs: certification.write_text("{}", encoding="utf-8"),
    )

    result = RunGenerationJob().execute(job.job_id, settings)

    assert result.state is WorkflowState.HUMAN_REVIEW
    assert selected == [("view-03",)]
    history = __import__("json").loads((generated / "repair_history.json").read_text())
    assert history["repairs"][0]["view_id"] == "view-03"
    assert history["repairs"][0]["parent_sha256"] != history["repairs"][0]["output_sha256"]


def test_the_job_forwards_its_authored_style_pack_to_the_prompt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both prompt call sites used to omit the pack, so every job ran on the strict base prompt
    whatever the caller chose. DesignFreedom and ContextPolicy were then reachable only from the
    CLI, and the API path could not express a marketing brief at all.
    """

    pack_path = Path("resource/style_packs/marketing_brochure.json")
    if not pack_path.is_file():
        pytest.skip("style pack catalog is not present in this checkout")

    seen: list[object] = []

    def _capture(_design_dna: Path, *_args: object, **kwargs: object) -> tuple[dict, str]:
        seen.append(kwargs.get("style_pack"))
        return {}, "prompt"

    monkeypatch.setattr(
        "v365_archviz.application.run_generation_job.build_refinement_prompt", _capture
    )
    job = SimpleNamespace(style_pack_ref=str(pack_path))
    from v365_archviz.application.run_generation_job import _authored_style, _composites_proxies

    pack = _authored_style(job)  # type: ignore[arg-type]

    assert pack is not None
    assert pack.design_freedom is DesignFreedom.DESIGN_WITHIN_ENVELOPE
    # The context policy has to travel with it, or the proxies are composited over a prompt that
    # asked the provider to build real neighbours.
    assert _composites_proxies(job) is pack.context_policy.composites_proxies  # type: ignore[arg-type]


def test_a_job_without_a_style_pack_keeps_the_strict_default() -> None:
    from v365_archviz.application.run_generation_job import _authored_style, _composites_proxies

    job = SimpleNamespace(style_pack_ref=None)

    assert _authored_style(job) is None  # type: ignore[arg-type]
    assert _composites_proxies(job) is True  # type: ignore[arg-type]
