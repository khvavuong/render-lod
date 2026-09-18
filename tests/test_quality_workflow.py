from pathlib import Path
from types import SimpleNamespace

from v365_archviz.application.camera_candidates import propose_candidates, select_view_set
from v365_archviz.application.create_generation_job import CreateGenerationJob
from v365_archviz.application.plan_cameras import _outward_clearance
from v365_archviz.application.run_generation_job import _authored_style, _JobPaths
from v365_archviz.domain.photography_pack import RoleFraming
from v365_archviz.domain.style_pack import DesignFreedom, StylePack
from v365_archviz.domain.workflow import GenerationProfile, ViewRole, ViewSet
from v365_archviz.providers.local_jobs import LocalJobRepository


def test_marketing_jobs_snapshot_the_effective_design_brief(tmp_path: Path) -> None:
    repository = LocalJobRepository(tmp_path / "metadata")
    view_set = ViewSet(view_set_id="views", design_revision="design", cameras=())
    source = Path(__file__).resolve().parents[1] / "resource/style_packs/marketing_photoreal.json"
    pack_path = tmp_path / "pack.json"
    pack = StylePack.load(source)
    pack_path.write_text(pack.to_json(), encoding="utf-8")
    arguments = dict(
        project_id="project",
        model_revision="model",
        design_revision="design",
        view_set=view_set,
        profile=GenerationProfile.MARKETING_HERO,
        style_pack_ref=str(pack_path),
    )
    first = CreateGenerationJob().execute(repository, **arguments)
    assert _authored_style(first.job).design_freedom is DesignFreedom.DESIGN_WITHIN_ENVELOPE
    changed = pack.model_copy(update={"intent": "A different client architectural direction"})
    pack_path.write_text(changed.to_json(), encoding="utf-8")
    second = CreateGenerationJob().execute(repository, **arguments)
    assert first.job.job_id != second.job.job_id
    assert _authored_style(repository.get(first.job.job_id)).intent == pack.intent
    first_paths = _JobPaths.from_job(tmp_path, first.job)
    second_paths = _JobPaths.from_job(tmp_path, second.job)
    assert first_paths.generated_root != second_paths.generated_root
    assert first_paths.render_root != second_paths.render_root
    assert first.job.view_set_id != second.job.view_set_id
    assert (
        ViewSet.model_validate_json(first_paths.view_set.read_text()).view_set_id
        == first.job.view_set_id
    )


def test_marketing_default_is_not_the_strict_tender_prompt(tmp_path: Path) -> None:
    result = CreateGenerationJob().execute(
        LocalJobRepository(tmp_path),
        project_id="project",
        model_revision="model",
        design_revision="design",
        view_set=ViewSet(view_set_id="views", design_revision="design", cameras=()),
        profile=GenerationProfile.MARKETING_HERO,
    )
    assert result.job.style_pack_snapshot
    assert _authored_style(result.job).context_policy.value == "resolve_proxies"


def test_camera_search_uses_width_depth_and_bearing() -> None:
    framing = RoleFraming(elevation_deg=20, focal_length_mm=35, target_width_coverage=0.7)
    args = dict(
        role=ViewRole.OVERALL,
        framing=framing,
        target=(0, 0, 4),
        bearings=(0, 90),
        distance_factors=(1,),
        elevation_offsets=(0,),
    )
    small = propose_candidates(bounds=((0, 0, 0), (40, 40, 11)), **args)
    large = propose_candidates(bounds=((0, 0, 0), (400, 200, 11)), **args)
    assert large[0].distance_m > small[0].distance_m * 5
    assert large[0].distance_m != large[1].distance_m
    assert select_view_set({ViewRole.OVERALL: [(large[0], 0)]}) == ()


def test_office_clearance_is_specific_to_its_outward_ray() -> None:
    blocker = SimpleNamespace(
        bounding_box=SimpleNamespace(minimum=(30, -5, 0), maximum=(50, 5, 12))
    )
    assert _outward_clearance((0, 0, 1.85), (1, 0, 0), [blocker]) == 29
    assert _outward_clearance((0, 0, 1.85), (0, 1, 0), [blocker]) == float("inf")
