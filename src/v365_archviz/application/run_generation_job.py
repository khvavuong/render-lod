"""Execute and resume a complete local generation job."""

from __future__ import annotations

import hashlib
import io
import json
import logging
from collections.abc import Callable
from pathlib import Path

from PIL import Image

from v365_archviz.application.brand_deliverables import BrandDeliverables
from v365_archviz.application.brand_watermark import BrandWatermark
from v365_archviz.application.build_control_pack import BuildControlPack
from v365_archviz.application.build_correspondence import BuildCorrespondenceIndex
from v365_archviz.application.compose_viewset_board import ComposeViewSetBoard
from v365_archviz.application.create_certification_report import CreateCertificationReport
from v365_archviz.application.evaluate_consistency import EvaluateConsistency
from v365_archviz.application.plan_cameras import PlanStandardCameras
from v365_archviz.application.promote_quality_baseline import PromoteQualityBaseline
from v365_archviz.application.protect_refinement import ProtectRefinement
from v365_archviz.application.realism_parity import (
    CheckRealismParity,
    correction_prompt,
    record_regeneration,
)
from v365_archviz.application.refine_viewset import RefineViewSet, select_master_view_ids
from v365_archviz.application.refinement_prompt import build_refinement_prompt
from v365_archviz.application.validate_conditioning import ValidateConditioningViewSet
from v365_archviz.application.validate_viewset import ValidateGeneratedViewSet
from v365_archviz.artifacts import atomic_write
from v365_archviz.config import Settings
from v365_archviz.domain.jobs import GenerationJob
from v365_archviz.domain.style_pack import StylePack
from v365_archviz.domain.workflow import Camera, ViewRole, ViewSet, WorkflowState
from v365_archviz.errors import V365Error
from v365_archviz.providers.gemini_realism_judge import GeminiRealismJudge
from v365_archviz.providers.image_factory import create_image_renderer
from v365_archviz.providers.local_blender_conditioning import create_conditioning_renderer
from v365_archviz.providers.local_jobs import LocalJobRepository

logger = logging.getLogger(__name__)

#: Each studio view judged against the concept master, and whether it was generated again.
REALISM_REPORT = "realism_parity.json"


def _authored_style(job: GenerationJob) -> StylePack | None:
    """Load the style pack this job was submitted with, if any.

    Both prompt call sites used to omit it, so every job ran on the built-in strict base prompt
    whatever the caller chose, and `composite_context_proxy` was hardcoded true at all three
    protection call sites. The effect was that DesignFreedom and ContextPolicy — the whole
    authored-customisation layer — were reachable only from the CLI and never from the API.
    """

    if getattr(job, "style_pack_snapshot", None):
        return StylePack.model_validate_json(job.style_pack_snapshot)
    if not job.style_pack_ref:
        return None
    return StylePack.load(Path(job.style_pack_ref))


def _composites_proxies(job: GenerationJob) -> bool:
    """Whether authored context volumes are composited for this job's context policy."""

    pack = _authored_style(job)
    return True if pack is None else pack.context_policy.composites_proxies


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

        if job.generation_policy == "reference-led-proposal-v1":
            if (paths.generated_root / "selected_shots.json").is_file():
                from v365_archviz.application.reference_delivery import generate_registered

                return generate_registered(repository, job, settings, paths)
            from v365_archviz.application.run_reference_proposal import run_proposal

            return run_proposal(repository, job, settings, paths, view_set)

        if job.state in {WorkflowState.RENDERING_PASSES, WorkflowState.GENERATING_VIEWSET}:
            view_set = self._ensure_conditioning(paths, view_set, job, settings)

        if job.state is WorkflowState.RENDERING_PASSES:
            job = self._advance(
                repository,
                job,
                WorkflowState.GENERATING_VIEWSET,
                paths.render_root / "correspondence_index.json",
                paths.render_root / "conditioning_qa.json",
            )

        if job.state is WorkflowState.GENERATING_VIEWSET:
            style_pack = _authored_style(job)
            _, prompt = build_refinement_prompt(paths.design_dna, style_pack=style_pack)
            references = tuple(Path(value) for value in job.reference_image_refs)
            reference_pairs = tuple(zip(references, job.reference_roles, strict=True))
            review_path = paths.generated_root / "design_master_review.json"
            review = self._read_master_review(review_path)
            if review.get("view_set_id") != job.view_set_id:
                review = {}
            if not review.get("approved", False):
                site_master_id, facade_master_id = select_master_view_ids(
                    paths.render_root, view_set.cameras
                )
                stored_master_ids = review.get("master_view_ids", {})
                stored_master_refs = review.get("master_image_refs", {})
                approved_master_types = review.get("approved_master_types", [])
                stored_site_ref = (
                    stored_master_refs.get("site") if isinstance(stored_master_refs, dict) else None
                )
                preserve_site = (
                    isinstance(approved_master_types, list)
                    and "site" in approved_master_types
                    and isinstance(stored_master_ids, dict)
                    and stored_master_ids.get("site") == site_master_id
                    and isinstance(stored_site_ref, str)
                    and Path(stored_site_ref).is_file()
                )
                generated_manifest_path = paths.generated_root / "viewset_generation_manifest.json"
                with create_image_renderer(settings, job.image_provider) as renderer:
                    if preserve_site:
                        assert isinstance(stored_site_ref, str)
                        site_master_path = Path(stored_site_ref)
                    else:
                        site_references = tuple(
                            path
                            for path, role in reference_pairs
                            if role == "context_realism_reference"
                        )
                        generated = RefineViewSet().execute(
                            renderer,
                            paths.render_root,
                            paths.generated_root,
                            paths.view_set,
                            paths.design_dna,
                            job.model_revision,
                            prompt,
                            profile=job.profile,
                            view_ids=(site_master_id,),
                            reference_images=site_references,
                            style_pack=style_pack,
                            attach_context_guide=style_pack is None
                            or style_pack.context_policy.sends_composition_guide,
                        )
                        generated_manifest_path = generated.manifest_path
                        site_master_path = self._refined_image(
                            paths.generated_root / site_master_id
                        )
                    if facade_master_id != site_master_id:
                        # The facade master is derived from the already generated site master.
                        # This makes the two approval images one identity chain instead of two
                        # unrelated Gemini generations.
                        facade_references = tuple(
                            path
                            for path, role in reference_pairs
                            if role == "factory_design_reference"
                        )
                        generated = RefineViewSet().execute(
                            renderer,
                            paths.render_root,
                            paths.generated_root,
                            paths.view_set,
                            paths.design_dna,
                            job.model_revision,
                            prompt,
                            profile=job.profile,
                            view_ids=(facade_master_id,),
                            reference_images=facade_references,
                            style_pack=style_pack,
                            attach_context_guide=style_pack is None
                            or style_pack.context_policy.sends_composition_guide,
                            approved_master_path=site_master_path,
                            approved_master_view_id=site_master_id,
                        )
                        generated_manifest_path = generated.manifest_path
                protected = ProtectRefinement().execute(
                    paths.render_root,
                    paths.generated_root,
                    restore_locked_pixels=False,
                    composite_context_proxy=_composites_proxies(job),
                )
                master_paths = {
                    "site": self._refined_image(paths.generated_root / site_master_id),
                    "facade": self._refined_image(paths.generated_root / facade_master_id),
                }
                facade_quality_standard = (
                    paths.generated_root
                    / f"approved_facade_quality_master{master_paths['facade'].suffix}"
                )
                atomic_write(
                    facade_quality_standard,
                    master_paths["facade"].read_bytes(),
                )
                master_path = paths.generated_root / "approved_master_identity.jpg"
                self._compose_master_identity(master_paths, master_path)
                atomic_write(
                    review_path,
                    json.dumps(
                        {
                            "schema_version": "1.0.0",
                            "view_set_id": job.view_set_id,
                            "status": "pending",
                            "approved": False,
                            "approved_master_types": (["site"] if preserve_site else []),
                            "master_view_id": site_master_id,
                            "master_image_ref": str(master_path),
                            "master_view_ids": {
                                "site": site_master_id,
                                "facade": facade_master_id,
                            },
                            "master_image_refs": {
                                role: str(path) for role, path in master_paths.items()
                            },
                            "quality_standard": {
                                "role": "facade_quality_master",
                                "view_id": facade_master_id,
                                "image_ref": str(facade_quality_standard),
                                "criteria": [
                                    "photographic_material_response",
                                    "restrained_buildable_facade_detail",
                                    "clean_natural_daylight",
                                    "credible_industrial_decor",
                                    "consistent_palette_and_finish",
                                ],
                            },
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
                    generated_manifest_path,
                    protected.manifest_path,
                    review_path,
                    master_path,
                    facade_quality_standard,
                )
            else:
                master_view_id = str(review["master_view_id"])
                master_path = Path(str(review["master_image_ref"]))
                stored_master_ids = review.get("master_view_ids")
                master_id_values = (
                    stored_master_ids.values()
                    if isinstance(stored_master_ids, dict)
                    else (master_view_id,)
                )
                master_view_ids = {str(item) for item in master_id_values}
                remaining_view_ids = tuple(
                    camera.view_id
                    for camera in view_set.cameras
                    if camera.view_id not in master_view_ids
                )
                stored_master_refs = review.get("master_image_refs")
                master_refs = (
                    {str(role): Path(str(path)) for role, path in stored_master_refs.items()}
                    if isinstance(stored_master_refs, dict)
                    else {"site": master_path, "facade": master_path}
                )
                stored_quality_standard = review.get("quality_standard")
                facade_quality_standard = (
                    Path(str(stored_quality_standard["image_ref"]))
                    if isinstance(stored_quality_standard, dict)
                    and stored_quality_standard.get("image_ref")
                    else master_refs.get("facade", master_path)
                )
                reference_images_by_view = {
                    camera.view_id: tuple(
                        tuple(
                            dict.fromkeys(
                                (
                                    *(
                                        path
                                        for path, role in reference_pairs
                                        if role
                                        == (
                                            "context_realism_reference"
                                            if camera.role in {ViewRole.OVERALL, ViewRole.DETAIL}
                                            else "factory_design_reference"
                                        )
                                    ),
                                    facade_quality_standard,
                                )
                            )
                        )[:2]
                    )
                    for camera in view_set.cameras
                    if camera.view_id in remaining_view_ids
                }
                stored_master_ids = review.get("master_view_ids")
                typed_master_ids = (
                    {str(role): str(view_id) for role, view_id in stored_master_ids.items()}
                    if isinstance(stored_master_ids, dict)
                    else {"site": master_view_id, "facade": master_view_id}
                )
                remaining_groups = (
                    (
                        "site",
                        tuple(
                            camera.view_id
                            for camera in view_set.cameras
                            if camera.view_id in remaining_view_ids
                            and camera.role in {ViewRole.OVERALL, ViewRole.DETAIL}
                        ),
                    ),
                    (
                        "facade",
                        tuple(
                            camera.view_id
                            for camera in view_set.cameras
                            if camera.view_id in remaining_view_ids
                            and camera.role not in {ViewRole.OVERALL, ViewRole.DETAIL}
                        ),
                    ),
                )
                with create_image_renderer(settings, job.image_provider) as renderer:

                    def generate(view_ids: tuple[str, ...], view_prompt: str) -> Path | None:
                        manifest_path = None
                        for master_type, group_view_ids in remaining_groups:
                            selected = tuple(item for item in group_view_ids if item in view_ids)
                            if not selected:
                                continue
                            manifest_path = (
                                RefineViewSet()
                                .execute(
                                    renderer,
                                    paths.render_root,
                                    paths.generated_root,
                                    paths.view_set,
                                    paths.design_dna,
                                    job.model_revision,
                                    view_prompt,
                                    profile=job.profile,
                                    view_ids=selected,
                                    style_pack=style_pack,
                                    attach_context_guide=style_pack is None
                                    or style_pack.context_policy.sends_composition_guide,
                                    reference_images=(),
                                    reference_images_by_view=reference_images_by_view,
                                    approved_master_path=master_refs.get(master_type, master_path),
                                    approved_master_view_id=typed_master_ids.get(
                                        master_type, master_view_id
                                    ),
                                    quality_standard_path=facade_quality_standard,
                                )
                                .manifest_path
                            )
                        return manifest_path

                    generated_manifest = generate(remaining_view_ids, prompt)
                    if generated_manifest is None:
                        raise V365Error("approved Design Masters left no views to generate")
                    if review.get("approved_by") == "concept_selection":
                        generated_manifest = (
                            self._match_master_realism(
                                settings,
                                paths,
                                remaining_view_ids,
                                master_refs.get("site", master_path),
                                lambda view_id, notes: generate(
                                    (view_id,), correction_prompt(prompt, notes)
                                ),
                            )
                            or generated_manifest
                        )
                protected = ProtectRefinement().execute(
                    paths.render_root,
                    paths.generated_root,
                    restore_locked_pixels=False,
                    composite_context_proxy=_composites_proxies(job),
                )
                job = self._advance(
                    repository,
                    job,
                    WorkflowState.VALIDATING,
                    generated_manifest,
                    protected.manifest_path,
                    *(
                        (paths.generated_root / REALISM_REPORT,)
                        if (paths.generated_root / REALISM_REPORT).is_file()
                        else ()
                    ),
                )

        if job.state is WorkflowState.REPAIRING:
            repair_path = paths.generated_root / "manual_repair_request.json"
            try:
                repair = json.loads(repair_path.read_text(encoding="utf-8"))
                repair_view_id = str(repair["view_id"])
                instruction = str(repair.get("instruction", "")).strip()
            except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
                raise V365Error("targeted repair request is missing or invalid") from exc
            cameras = {camera.view_id: camera for camera in view_set.cameras}
            if repair_view_id not in cameras:
                raise V365Error("targeted repair view does not belong to this view set")
            review = self._read_master_review(paths.generated_root / "design_master_review.json")
            if not review.get("approved", False):
                raise V365Error("Design Masters must be approved before targeted repair")
            master_ids = review.get("master_view_ids", {})
            repair_master_refs = review.get("master_image_refs", {})
            if not isinstance(master_ids, dict) or not isinstance(repair_master_refs, dict):
                raise V365Error("approved Design Master lineage is incomplete")
            camera = cameras[repair_view_id]
            preferred_type = (
                "site" if camera.role in {ViewRole.OVERALL, ViewRole.DETAIL} else "facade"
            )
            alternate_type = "facade" if preferred_type == "site" else "site"
            anchor_type = (
                alternate_type
                if str(master_ids.get(preferred_type)) == repair_view_id
                else preferred_type
            )
            anchor_path = Path(str(repair_master_refs.get(anchor_type, "")))
            if not anchor_path.is_file():
                raise V365Error("targeted repair has no valid approved identity anchor")
            quality = review.get("quality_standard", {})
            quality_path = (
                Path(str(quality.get("image_ref")))
                if isinstance(quality, dict) and quality.get("image_ref")
                else None
            )
            style_pack = _authored_style(job)
            _, prompt = build_refinement_prompt(paths.design_dna, style_pack=style_pack)
            correction = (
                instruction
                or "Correct only the QA issue visible in this view while improving "
                "photographic realism."
            )
            prompt = (
                f"{prompt}\n\nQA-DRIVEN TARGETED REPAIR\n{correction}\n"
                "Preserve every camera, mass, roof, opening, gate, fence, road, landscape boundary "
                "and all pixels outside the affected visual issue. Do not redesign the project."
            )
            source_image = self._refined_image(paths.generated_root / repair_view_id)
            source_hash = hashlib.sha256(source_image.read_bytes()).hexdigest()
            external_role = (
                "context_realism_reference"
                if preferred_type == "site"
                else "factory_design_reference"
            )
            external_references = tuple(
                Path(path)
                for path, role in zip(job.reference_image_refs, job.reference_roles, strict=True)
                if role == external_role
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
                    view_ids=(repair_view_id,),
                    style_pack=style_pack,
                    attach_context_guide=style_pack is None
                    or style_pack.context_policy.sends_composition_guide,
                    reference_images=external_references,
                    approved_master_path=anchor_path,
                    approved_master_view_id=str(master_ids.get(anchor_type, repair_view_id)),
                    quality_standard_path=quality_path,
                )
            protected = ProtectRefinement().execute(
                paths.render_root,
                paths.generated_root,
                restore_locked_pixels=False,
                composite_context_proxy=_composites_proxies(job),
            )
            repaired_image = self._refined_image(paths.generated_root / repair_view_id)
            self._append_repair_lineage(
                paths.generated_root / "repair_history.json",
                view_set_id=job.view_set_id,
                view_id=repair_view_id,
                attempt=job.attempt,
                instruction=correction,
                parent_sha256=source_hash,
                output_sha256=hashlib.sha256(repaired_image.read_bytes()).hexdigest(),
                generation_manifest=generated.manifest_path,
            )
            job = self._advance(
                repository,
                job,
                WorkflowState.VALIDATING,
                generated.manifest_path,
                protected.manifest_path,
                repair_path,
                paths.generated_root / "repair_history.json",
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
            job = self._advance(
                repository,
                job,
                WorkflowState.HUMAN_REVIEW,
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
            if self._read_master_review(paths.generated_root / "final_viewset_review.json").get(
                "approved", False
            ):
                PromoteQualityBaseline().execute(
                    settings.artifact_dir,
                    job.model_revision,
                    job.design_revision,
                    job.view_set_id,
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

    def _match_master_realism(
        self,
        settings: Settings,
        paths: _JobPaths,
        view_ids: tuple[str, ...],
        master: Path,
        regenerate: Callable[[str, str], Path | None],
    ) -> Path | None:
        """Generate once more, with a correction, each view that fell short of the master.

        Returns the manifest of the last regeneration, or None when nothing was regenerated.
        Proofing needs a Gemini key; without one the set is delivered as generated.
        """

        if not settings.gemini_api_key:
            return None
        parity = CheckRealismParity().execute(
            GeminiRealismJudge(settings),
            {view_id: self._refined_image(paths.generated_root / view_id) for view_id in view_ids},
            master,
            paths.generated_root / REALISM_REPORT,
        )
        manifest = None
        for view_id, notes in parity.failed.items():
            manifest = regenerate(view_id, notes) or manifest
        if parity.failed:
            record_regeneration(parity.report_path, parity.failed)
        return manifest

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

    @staticmethod
    def _compose_master_identity(master_paths: dict[str, Path], target: Path) -> None:
        images = []
        for role in ("site", "facade"):
            with Image.open(master_paths[role]) as source:
                images.append(source.convert("RGB"))
        height = min(image.height for image in images)
        resized = [
            image.resize(
                (round(image.width * height / image.height), height),
                Image.Resampling.LANCZOS,
            )
            for image in images
        ]
        board = Image.new("RGB", (sum(image.width for image in resized), height), "white")
        offset = 0
        for image in resized:
            board.paste(image, (offset, 0))
            offset += image.width
        buffer = io.BytesIO()
        board.save(buffer, format="JPEG", quality=95, optimize=True)
        atomic_write(target, buffer.getvalue())

    @staticmethod
    def _append_repair_lineage(
        path: Path,
        *,
        view_set_id: str,
        view_id: str,
        attempt: int,
        instruction: str,
        parent_sha256: str,
        output_sha256: str,
        generation_manifest: Path,
    ) -> None:
        try:
            history = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            history = {"schema_version": "1.0.0", "repairs": []}
        repairs = history.get("repairs", [])
        if not isinstance(repairs, list):
            repairs = []
        repairs.append(
            {
                "view_set_id": view_set_id,
                "view_id": view_id,
                "attempt": attempt,
                "instruction": instruction,
                "parent_sha256": parent_sha256,
                "output_sha256": output_sha256,
                "generation_manifest": str(generation_manifest),
            }
        )
        history["repairs"] = repairs
        atomic_write(
            path,
            json.dumps(history, ensure_ascii=False, indent=2).encode("utf-8") + b"\n",
        )

    def _ensure_conditioning(
        self,
        paths: _JobPaths,
        view_set: ViewSet,
        job: GenerationJob,
        settings: Settings,
    ) -> ViewSet:
        """Render the conditioning passes and refuse to spend money on a bad frame.

        Returns the view set the passes were taken through, which is not always
        the one that came in: a job that carries no snapshot of its own points at
        the design's shared camera file, and that file is whatever the planner
        wrote the last time anyone asked. A job created before a planner fix and
        retried after it was still framed by the old answer, so the fix could not
        reach it and the same views failed with the same numbers.
        """

        if not job.view_set_snapshot:
            view_set = PlanStandardCameras().execute(
                paths.scene,
                paths.design_dna,
                output_path=paths.view_set,
            )
        pack = _authored_style(job)
        facade_mode = (
            "envelope_program"
            if pack and pack.design_freedom.value == "design_within_envelope"
            else "authored"
        )
        try:
            render_manifest = json.loads(
                (paths.render_root / "render_manifest.json").read_text(encoding="utf-8")
            )
        except (OSError, ValueError):
            render_manifest = {}
        mode_matches = render_manifest.get("facade_mode", "authored") == facade_mode
        script_path = Path(__file__).resolve().parents[3] / "scripts/blender/render_conditioning.py"
        script_matches = (
            render_manifest.get("renderer_script_sha256")
            == hashlib.sha256(script_path.read_bytes()).hexdigest()
        )
        if (
            not script_matches
            or not mode_matches
            or not self._conditioning_complete(paths, view_set)
        ):
            create_conditioning_renderer(settings.conditioning_backend).execute(
                paths.scene,
                paths.design_dna,
                paths.view_set,
                paths.render_root,
                job.render_profile,
                facade_mode=facade_mode,
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
        return view_set

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
    def _conditioning_complete(paths: _JobPaths, view_set: ViewSet) -> bool:
        render_root = paths.render_root
        manifest_path = render_root / "render_manifest.json"
        if not manifest_path.is_file():
            return False
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        # Camera values can remain equal while renderer semantics or context composition changes.
        # The versioned view-set identity is therefore part of the conditioning cache key.
        if manifest.get("view_set_id") != view_set.view_set_id:
            return False
        # And the identity can remain equal while the camera values change: it is
        # built from the design revision and a version tag, neither of which moves
        # when the planner is corrected. A job retried after such a correction
        # re-used renders taken through the old cameras and was then judged
        # against the new ones — which is how a fixed camera kept failing with the
        # exact numbers of the fault that had been fixed. The inputs the renderer
        # hashed are what decides whether its output still stands.
        for key, source in (
            ("view_set_sha256", paths.view_set),
            ("scene_sha256", paths.scene),
            ("design_dna_sha256", paths.design_dna),
        ):
            recorded = manifest.get(key)
            if not isinstance(recorded, str) or not source.is_file():
                return False
            if recorded != hashlib.sha256(source.read_bytes()).hexdigest():
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
            "project_locked_mask.png",
            "project_designable_mask.png",
            "context_ground_mask.png",
            "context_proxy_mask.png",
            "layer_authority_manifest.json",
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
        view_set_path = design_root / "view_set.json"
        if job.view_set_snapshot:
            view_set_path = artifact_dir / "job_inputs" / job.job_id / "view_set.json"
            atomic_write(view_set_path, job.view_set_snapshot.encode("utf-8") + b"\n")
        render_root = artifact_dir / "renders" / job.model_revision / job.design_revision
        generated_root = artifact_dir / "generated" / job.model_revision / job.design_revision
        if job.output_namespace:
            render_root = render_root / job.output_namespace
            generated_root = generated_root / job.output_namespace
        return cls(
            scene=scene_root / "canonical_scene.json",
            design_dna=design_root / "design_dna.json",
            view_set=view_set_path,
            render_root=render_root,
            generated_root=generated_root,
        )
