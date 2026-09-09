"""Execute and resume a complete local generation job."""

from __future__ import annotations

import logging
from pathlib import Path

from v365_archviz.application.assemble_video import AssembleVideo
from v365_archviz.application.brand_deliverables import BrandDeliverables
from v365_archviz.application.brand_watermark import BrandWatermark
from v365_archviz.application.build_correspondence import BuildCorrespondenceIndex
from v365_archviz.application.compose_viewset_board import ComposeViewSetBoard
from v365_archviz.application.evaluate_consistency import EvaluateConsistency
from v365_archviz.application.generate_video import GenerateVideoShots
from v365_archviz.application.plan_video import PlanVideo
from v365_archviz.application.refine_viewset import RefineViewSet
from v365_archviz.application.refinement_prompt import build_refinement_prompt
from v365_archviz.application.validate_viewset import ValidateGeneratedViewSet
from v365_archviz.config import Settings
from v365_archviz.domain.jobs import GenerationJob
from v365_archviz.domain.workflow import ViewSet, WorkflowState
from v365_archviz.errors import V365Error
from v365_archviz.providers.docker_conditioning import DockerConditioningRenderer
from v365_archviz.providers.gemini import GeminiImageRenderer
from v365_archviz.providers.local_jobs import LocalJobRepository
from v365_archviz.providers.veo import VeoVideoRenderer

logger = logging.getLogger(__name__)


class RunGenerationJob:
    """Run every expensive stage while persisting a resumable state boundary."""

    def execute(self, job_id: str, settings: Settings | None = None) -> GenerationJob:
        resolved_settings = settings or Settings.from_env()
        repository = LocalJobRepository(resolved_settings.artifact_dir / "metadata")
        job = repository.get(job_id)
        try:
            return self._run(repository, job, resolved_settings)
        except Exception as exc:
            logger.exception("generation job %s failed", job_id)
            current = repository.get(job_id)
            if current.state not in {WorkflowState.COMPLETED, WorkflowState.FAILED}:
                current = current.transition(
                    WorkflowState.FAILED,
                    error_code=type(exc).__name__,
                    error_message=self._safe_error(exc),
                )
                repository.save(current)
            return current

    def _run(
        self,
        repository: LocalJobRepository,
        job: GenerationJob,
        settings: Settings,
    ) -> GenerationJob:
        paths = _JobPaths.from_job(settings.artifact_dir, job)
        view_set = ViewSet.model_validate_json(paths.view_set.read_text(encoding="utf-8"))

        if job.state is WorkflowState.RENDERING_PASSES:
            if not self._conditioning_complete(paths.render_root, view_set):
                DockerConditioningRenderer().execute(
                    paths.scene,
                    paths.design_dna,
                    paths.view_set,
                    paths.render_root,
                )
            correspondence = BuildCorrespondenceIndex().execute(
                paths.scene,
                paths.view_set,
                paths.render_root,
            )
            job = self._advance(
                repository,
                job,
                WorkflowState.GENERATING_VIEWSET,
                correspondence.manifest_path,
            )

        if job.state is WorkflowState.GENERATING_VIEWSET:
            _, prompt = build_refinement_prompt(paths.design_dna)
            with GeminiImageRenderer(settings) as renderer:
                generated = RefineViewSet().execute(
                    renderer,
                    paths.render_root,
                    paths.generated_root,
                    paths.view_set,
                    paths.design_dna,
                    job.model_revision,
                    prompt,
                    profile=job.profile,
                )
            job = self._advance(
                repository,
                job,
                WorkflowState.VALIDATING,
                generated.manifest_path,
            )

        if job.state is WorkflowState.VALIDATING:
            validation = ValidateGeneratedViewSet().execute(
                paths.render_root,
                paths.generated_root,
                paths.view_set,
                paths.design_dna,
            )
            if not validation.passed:
                raise V365Error(
                    f"generated view set failed {validation.error_count} technical QA checks"
                )
            consistency = EvaluateConsistency().execute(
                validation.report_path,
                job.model_revision,
                job.view_set_id,
            )
            job = self._advance(
                repository,
                job,
                WorkflowState.COMPOSING_BOARD,
                validation.report_path,
                consistency.report_path,
            )

        if job.state is WorkflowState.COMPOSING_BOARD:
            board = ComposeViewSetBoard().execute(
                paths.generated_root,
                paths.board,
            )
            branded = BrandDeliverables().execute(
                BrandWatermark(),
                paths.generated_root,
                board_path=board.board_path,
            )
            job = self._advance(
                repository,
                job,
                (
                    WorkflowState.GENERATING_VIDEO
                    if settings.video_generation_enabled
                    else WorkflowState.COMPLETED
                ),
                branded.manifest_path,
                paths.board,
            )

        if job.state is WorkflowState.GENERATING_VIDEO:
            video_plan = PlanVideo().execute(
                paths.generated_root,
                paths.view_set,
                settings.artifact_dir / "videos",
                settings,
            )
            video_root = video_plan.plan_path.parent
            with VeoVideoRenderer(settings) as renderer:
                generated_video = GenerateVideoShots().execute(
                    renderer,
                    video_plan.plan_path,
                    video_root,
                    poll_interval_seconds=settings.veo_poll_interval_seconds,
                    timeout_seconds=settings.veo_timeout_seconds,
                )
            assembled = AssembleVideo().execute(
                video_plan.plan_path,
                video_root,
                video_root / "showreel.mp4",
            )
            branded = BrandDeliverables().execute(
                BrandWatermark(),
                paths.generated_root,
                board_path=paths.board,
                video_path=assembled.video_path,
            )
            job = self._advance(
                repository,
                job,
                WorkflowState.COMPLETED,
                video_plan.plan_path,
                generated_video.manifest_path,
                assembled.report_path,
                assembled.video_path,
                branded.manifest_path,
            )
        return job

    @staticmethod
    def _advance(
        repository: LocalJobRepository,
        job: GenerationJob,
        state: WorkflowState,
        *artifact_paths: Path,
    ) -> GenerationJob:
        refs = tuple(dict.fromkeys((*job.artifact_refs, *(str(path) for path in artifact_paths))))
        updated = job.transition(state, artifact_refs=refs)
        repository.save(updated)
        return updated

    @staticmethod
    def _conditioning_complete(render_root: Path, view_set: ViewSet) -> bool:
        names = ("base_rgb.png", "depth.png", "instance_id.png", "semantic.png", "edges.png")
        return all(
            (render_root / camera.view_id / name).is_file()
            for camera in view_set.cameras
            for name in names
        )

    @staticmethod
    def _safe_error(exc: Exception) -> str:
        message = str(exc).strip() or type(exc).__name__
        return message[-2000:]


class _JobPaths:
    def __init__(
        self,
        *,
        scene: Path,
        design_dna: Path,
        view_set: Path,
        render_root: Path,
        generated_root: Path,
    ) -> None:
        self.scene = scene
        self.design_dna = design_dna
        self.view_set = view_set
        self.render_root = render_root
        self.generated_root = generated_root
        self.board = generated_root / "viewset_board.jpg"

    @classmethod
    def from_job(cls, artifact_dir: Path, job: GenerationJob) -> _JobPaths:
        scene_root = artifact_dir / "scenes" / job.model_revision
        design_root = scene_root / "designs" / job.design_revision
        return cls(
            scene=scene_root / "canonical_scene.json",
            design_dna=design_root / "design_dna.json",
            view_set=design_root / "view_set.json",
            render_root=artifact_dir / "renders" / job.model_revision / job.design_revision,
            generated_root=artifact_dir / "generated" / job.model_revision / job.design_revision,
        )
