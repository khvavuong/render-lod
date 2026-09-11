"""Execute and resume a complete local generation job."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from v365_archviz.application.brand_deliverables import BrandDeliverables
from v365_archviz.application.brand_watermark import BrandWatermark
from v365_archviz.application.build_control_pack import BuildControlPack
from v365_archviz.application.build_correspondence import BuildCorrespondenceIndex
from v365_archviz.application.compose_viewset_board import ComposeViewSetBoard
from v365_archviz.application.create_certification_report import CreateCertificationReport
from v365_archviz.application.evaluate_consistency import EvaluateConsistency
from v365_archviz.application.protect_refinement import ProtectRefinement
from v365_archviz.application.refine_viewset import RefineViewSet, _select_master_view_id
from v365_archviz.application.refinement_prompt import build_refinement_prompt
from v365_archviz.application.validate_conditioning import ValidateConditioningViewSet
from v365_archviz.application.validate_viewset import ValidateGeneratedViewSet
from v365_archviz.artifacts import atomic_write
from v365_archviz.config import Settings
from v365_archviz.domain.jobs import GenerationJob
from v365_archviz.domain.workflow import Camera, ViewSet, WorkflowState
from v365_archviz.errors import V365Error
from v365_archviz.providers.image_factory import create_image_renderer
from v365_archviz.providers.local_blender_conditioning import create_conditioning_renderer
from v365_archviz.providers.local_jobs import LocalJobRepository

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

        if job.state in {WorkflowState.RENDERING_PASSES, WorkflowState.GENERATING_VIEWSET}:
            self._ensure_conditioning(paths, view_set, job, settings)

        if job.state is WorkflowState.RENDERING_PASSES:
            job = self._advance(
                repository,
                job,
                WorkflowState.GENERATING_VIEWSET,
                paths.render_root / "correspondence_index.json",
                paths.render_root / "conditioning_qa.json",
            )

        if job.state is WorkflowState.GENERATING_VIEWSET:
            _, prompt = build_refinement_prompt(paths.design_dna)
            review_path = paths.generated_root / "design_master_review.json"
            review = self._read_master_review(review_path)
            if not review.get("approved", False):
                master_view_id = _select_master_view_id(paths.render_root, view_set.cameras)
                with create_image_renderer(settings, job.image_provider) as renderer:
                    generated = RefineViewSet().execute(
                        renderer,
                        paths.render_root,
                        paths.generated_root,
                        paths.view_set,
                        paths.design_dna,
                        job.model_revision,
                        prompt,
                        profile=job.profile,
                        view_ids=(master_view_id,),
                    )
                protected = ProtectRefinement().execute(
                    paths.render_root,
                    paths.generated_root,
                    restore_locked_pixels=False,
                )
                master_path = self._refined_image(paths.generated_root / master_view_id)
                atomic_write(
                    review_path,
                    json.dumps(
                        {
                            "schema_version": "1.0.0",
                            "status": "pending",
                            "approved": False,
                            "master_view_id": master_view_id,
                            "master_image_ref": str(master_path),
                            "geometry_screen_passed": protected.rejected_count == 0,
                            "next_stage": "generate_remaining_views_after_explicit_approval",
                        },
                        ensure_ascii=False,
                        indent=2,
                    ).encode("utf-8")
                    + b"\n",
                )
                job = self._advance(
                    repository,
                    job,
                    WorkflowState.DESIGN_MASTER_REVIEW,
                    generated.manifest_path,
                    protected.manifest_path,
                    review_path,
                    master_path,
                )
            else:
                master_view_id = str(review["master_view_id"])
                master_path = Path(str(review["master_image_ref"]))
                remaining_view_ids = tuple(
                    camera.view_id
                    for camera in view_set.cameras
                    if camera.view_id != master_view_id
                )
                with create_image_renderer(settings, job.image_provider) as renderer:
                    generated = RefineViewSet().execute(
                        renderer,
                        paths.render_root,
                        paths.generated_root,
                        paths.view_set,
                        paths.design_dna,
                        job.model_revision,
                        prompt,
                        profile=job.profile,
                        view_ids=remaining_view_ids,
                        approved_master_path=master_path,
                        approved_master_view_id=master_view_id,
                    )
                protected = ProtectRefinement().execute(
                    paths.render_root,
                    paths.generated_root,
                    restore_locked_pixels=False,
                )
                job = self._advance(
                    repository,
                    job,
                    WorkflowState.VALIDATING,
                    generated.manifest_path,
                    protected.manifest_path,
                )

        if job.state is WorkflowState.VALIDATING:
            validation = ValidateGeneratedViewSet().execute(
                paths.render_root,
                paths.generated_root,
                paths.view_set,
                paths.design_dna,
            )
            consistency = EvaluateConsistency().execute(
                validation.report_path,
                job.model_revision,
                job.view_set_id,
            )
            certification_path = paths.generated_root / "certification_report.json"
            CreateCertificationReport().execute(
                consistency.report_path,
                validation.report_path,
                paths.generated_root / "protected_composite_manifest.json",
                certification_path,
            )
            target_state = (
                WorkflowState.COMPOSING_BOARD
                if validation.passed
                else WorkflowState.HUMAN_REVIEW
            )
            job = self._advance(
                repository,
                job,
                target_state,
                validation.report_path,
                consistency.report_path,
                certification_path,
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
                WorkflowState.COMPLETED,
                branded.manifest_path,
                paths.board,
            )

        # Jobs persisted by versions that coupled image and video generation must stop here.
        # The separate video endpoint is now the only path allowed to incur Veo cost.
        if job.state is WorkflowState.GENERATING_VIDEO:
            job = self._advance(repository, job, WorkflowState.COMPLETED)
        return job

    @staticmethod
    def _read_master_review(path: Path) -> dict[str, object]:
        if not path.is_file():
            return {}
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return document if isinstance(document, dict) else {}

    @staticmethod
    def _refined_image(view_directory: Path) -> Path:
        images = tuple(path for path in view_directory.glob("refined.*") if path.is_file())
        if len(images) != 1:
            raise V365Error(f"{view_directory.name} has no unique Design Master image")
        return images[0]

    def _ensure_conditioning(
        self,
        paths: _JobPaths,
        view_set: ViewSet,
        job: GenerationJob,
        settings: Settings,
    ) -> None:
        if not self._conditioning_complete(paths.render_root, view_set):
            create_conditioning_renderer(settings.conditioning_backend).execute(
                paths.scene,
                paths.design_dna,
                paths.view_set,
                paths.render_root,
                job.render_profile,
            )
            for camera in view_set.cameras:
                BuildControlPack().execute(paths.render_root / camera.view_id)
        BuildCorrespondenceIndex().execute(
            paths.scene,
            paths.view_set,
            paths.render_root,
        )
        conditioning_qa = ValidateConditioningViewSet().execute(
            paths.scene,
            paths.view_set,
            paths.render_root,
        )
        if not conditioning_qa.passed:
            failed = ", ".join(conditioning_qa.failed_view_ids)
            raise V365Error(f"camera preflight rejected views before paid generation: {failed}")

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
        if not (render_root / "render_manifest.json").is_file():
            return False
        names = (
            "base_rgb.png",
            "depth.png",
            "instance_id.png",
            "semantic.png",
            "semantic_id_manifest.json",
            "material_id.png",
            "material_id_manifest.json",
            "edges.png",
            "control_policy.png",
            "structure_guide.png",
            "locked_mask.png",
            "bounded_mask.png",
            "free_mask.png",
            "control_pack_manifest.json",
        )
        passes_exist = all(
            (render_root / camera.view_id / name).is_file()
            for camera in view_set.cameras
            for name in names
        )
        if not passes_exist:
            return False
        for camera in view_set.cameras:
            camera_path = render_root / camera.view_id / "camera.json"
            try:
                rendered_camera = Camera.model_validate_json(
                    camera_path.read_text(encoding="utf-8")
                )
            except (OSError, ValueError):
                return False
            if rendered_camera != camera:
                return False
        return True

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
