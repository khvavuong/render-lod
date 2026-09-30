"""Render Studio: concepts first, then the chosen concept through the user's shots.

This module composes the existing pipeline rather than adding a parallel one:

1. A concept is an ordinary job with a one-camera view set (the hero aerial,
   planned from the model alone and shared by every preset) for one preset's
   design brief. The worker renders its passes and generates the Design Master,
   then stops at DESIGN_MASTER_REVIEW. That master is the concept image.
2. Choosing a concept starts a second job for the same design revision whose
   view set is the concept's hero camera followed by the user's shots (proposed
   as four more aerials and one entrance view). The concept's master is copied
   in and recorded as already approved, so the worker renders every camera and
   generates only the remaining views, anchored to the image the user chose.
3. The set is finalized without branding: the board is composed and the job is
   completed, which is what the video endpoint requires.
"""

from __future__ import annotations

import hashlib
import json
import math
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import Field

from v365_archviz.application.compose_viewset_board import ComposeViewSetBoard
from v365_archviz.application.create_generation_job import CreateGenerationJob
from v365_archviz.application.import_scene_upload import context_element_ids
from v365_archviz.application.plan_cameras import PlanStandardCameras
from v365_archviz.application.plan_design import PlanDesign
from v365_archviz.application.run_generation_job import _JobPaths
from v365_archviz.artifacts import atomic_write
from v365_archviz.config import Settings
from v365_archviz.domain.common import DomainModel, Vec3
from v365_archviz.domain.design import DesignBrief
from v365_archviz.domain.jobs import GenerationJob
from v365_archviz.domain.scene import CanonicalScene, SceneElement, SemanticRole
from v365_archviz.domain.workflow import (
    Camera,
    GenerationProfile,
    RenderProfile,
    ViewRole,
    ViewSet,
    WorkflowState,
)
from v365_archviz.errors import InvalidModelError
from v365_archviz.providers.contracts import JobRepository

RESOURCE_DIRECTORY = Path(__file__).resolve().parents[3] / "resource"
PRESET_DIRECTORY = RESOURCE_DIRECTORY / "concept_presets"
#: Vietnamese place, climate and photographic register over the marketing geometry contract.
STUDIO_STYLE_PACK = RESOURCE_DIRECTORY / "style_packs" / "vietnam_marketing.json"
#: A real photograph of a Vietnamese industrial park. It anchors photographic realism and the
#: surroundings; the prompt forbids taking palette, facade or layout from it, so the five
#: concepts still differ. The same photograph is also the construction-detail reference for the
#: eye-level entrance view: without one, that view's only guide was the aerial master, and it
#: kept the flat surfaces of the conditioning render.
STUDIO_PHOTOGRAPH = RESOURCE_DIRECTORY / "studio_references" / "vietnam_industrial_context.jpg"
STUDIO_REFERENCES: tuple[tuple[Path, str], ...] = (
    (STUDIO_PHOTOGRAPH, "context_realism_reference"),
    (STUDIO_PHOTOGRAPH, "factory_design_reference"),
)
HERO_VIEW_ID = "view-01"
MAX_SHOTS = 11
#: The studio set after the concept: four more aerials around the project, then one eye-level
#: view at the entrance. Bearings are measured from the concept camera, so every aerial keeps its
#: distance and framing and only the side it looks from changes.
AERIAL_ORBIT_DEG: tuple[float, ...] = (90.0, 180.0, 270.0)
#: The fifth aerial looks from between the concept and the first orbit, higher, so it reads as
#: the masterplan rather than as a fifth three-quarter view.
MASTERPLAN_BEARING_DEG = 45.0
MASTERPLAN_PITCH_DEG = 58.0
MASTERPLAN_DISTANCE_SCALE = 1.1
DEFAULT_SENSOR_WIDTH_MM = 36.0
DEFAULT_ASPECT_RATIO = "16:9"
#: How much wider than the buildings' diagonal the concept aerial frames. The
#: planner's overview fits the whole site, and on a large lot with few buildings
#: that leaves the architecture too small to pass the camera check; a concept is
#: about the architecture.
CONCEPT_FRAME_MARGIN = 1.6


class ConceptPreset(DomainModel):
    schema_version: str = "1.0.0"
    preset_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    order: int = 0
    name: str = Field(min_length=1, max_length=80)
    summary: str = Field(min_length=1, max_length=240)
    brief: dict[str, Any]


def load_concept_presets(directory: Path = PRESET_DIRECTORY) -> tuple[ConceptPreset, ...]:
    presets = (
        ConceptPreset.model_validate_json(path.read_text(encoding="utf-8"))
        for path in directory.glob("*.json")
    )
    return tuple(sorted(presets, key=lambda preset: (preset.order, preset.preset_id)))


def find_concept_presets(preset_ids: tuple[str, ...]) -> tuple[ConceptPreset, ...]:
    presets = {preset.preset_id: preset for preset in load_concept_presets()}
    if unknown := [preset_id for preset_id in preset_ids if preset_id not in presets]:
        raise InvalidModelError(f"unknown concept presets: {unknown}")
    return tuple(presets[preset_id] for preset_id in preset_ids)


@dataclass(frozen=True, slots=True)
class StartedConcept:
    preset: ConceptPreset
    job: GenerationJob
    created: bool


@dataclass(frozen=True, slots=True)
class ShotSpec:
    position: Vec3
    target: Vec3
    focal_length_mm: float
    role: ViewRole = ViewRole.CUSTOM
    sensor_width_mm: float = DEFAULT_SENSOR_WIDTH_MM
    aspect_ratio: str = DEFAULT_ASPECT_RATIO


def _scene_path(settings: Settings, model_revision: str) -> Path:
    return settings.artifact_dir / "scenes" / model_revision / "canonical_scene.json"


def _design_directory(settings: Settings, model_revision: str, design_revision: str) -> Path:
    return settings.artifact_dir / "scenes" / model_revision / "designs" / design_revision


def _studio_directory(settings: Settings, model_revision: str) -> Path:
    return settings.artifact_dir / "scenes" / model_revision / "studio"


def _refined(directory: Path) -> Path:
    images = tuple(path for path in directory.glob("refined.*") if path.is_file())
    if len(images) != 1:
        raise InvalidModelError(f"{directory.name} has no single generated image")
    return images[0]


class StartConcepts:
    """Plan each preset's design and cameras, then queue its one-camera concept job."""

    def execute(
        self,
        settings: Settings,
        repository: JobRepository,
        *,
        model_revision: str,
        project_id: str,
        presets: tuple[ConceptPreset, ...],
        variant: int = 1,
    ) -> tuple[StartedConcept, ...]:
        scene_path = _scene_path(settings, model_revision)
        if not scene_path.is_file():
            raise FileNotFoundError("canonical scene not found")
        scene = CanonicalScene.model_validate_json(scene_path.read_text(encoding="utf-8"))
        # One camera for every concept of this model, so the five differ only in their design.
        hero = studio_hero(settings, scene, scene_path, model_revision)
        started: list[StartedConcept] = []
        for preset in presets:
            brief = DesignBrief.model_validate(
                {
                    **preset.brief,
                    "project_id": project_id,
                    "focus_building_ids": [],
                    "context_building_ids": list(context_element_ids(scene)),
                }
            )
            self._plan_design(settings, scene, scene_path, model_revision, brief)
            revision = PlanDesign.revision(scene, brief)
            concept_set = ViewSet(
                view_set_id=f"{revision}-concept-{variant}",
                design_revision=revision,
                cameras=(hero,),
            )
            created = CreateGenerationJob().execute(
                repository,
                project_id=project_id,
                model_revision=model_revision,
                design_revision=revision,
                view_set=concept_set,
                profile=GenerationProfile.MARKETING_HERO,
                render_profile=RenderProfile.STANDARD_EEVEE,
                image_provider=settings.image_provider,
                reference_image_refs=tuple(str(path) for path, _role in STUDIO_REFERENCES),
                reference_roles=tuple(role for _path, role in STUDIO_REFERENCES),
                style_pack_ref=str(STUDIO_STYLE_PACK),
            )
            job = created.job
            if created.created:
                job = job.transition(WorkflowState.RENDERING_PASSES)
                repository.save(job)
            started.append(StartedConcept(preset=preset, job=job, created=created.created))
        return tuple(started)

    @staticmethod
    def _plan_design(
        settings: Settings,
        scene: CanonicalScene,
        scene_path: Path,
        model_revision: str,
        brief: DesignBrief,
    ) -> None:
        """Compile the preset's design and its planned cameras, which the entrance view uses."""

        revision = PlanDesign.revision(scene, brief)
        design_directory = _design_directory(settings, model_revision, revision)
        brief_path = design_directory / "design_brief.json"
        design_path = design_directory / "design_dna.json"
        view_set_path = design_directory / "view_set.json"
        if not design_path.is_file():
            atomic_write(brief_path, brief.model_dump_json(indent=2).encode() + b"\n")
            PlanDesign().execute(scene_path, brief_path)
        if not view_set_path.is_file():
            PlanStandardCameras().execute(scene_path, design_path, output_path=view_set_path)


def studio_hero(
    settings: Settings, scene: CanonicalScene, scene_path: Path, model_revision: str
) -> Camera:
    """The concept camera: planned from the model alone, so no preset can move it."""

    view_set_path = _studio_directory(settings, model_revision) / "view_set.json"
    if not view_set_path.is_file():
        PlanStandardCameras().execute(scene_path, output_path=view_set_path)
    planned = ViewSet.model_validate_json(view_set_path.read_text(encoding="utf-8"))
    hero = next(
        (camera for camera in planned.cameras if camera.role is ViewRole.OVERALL),
        planned.cameras[0],
    )
    return frame_buildings(hero, scene).model_copy(update={"view_id": HERO_VIEW_ID})


def orbit(
    camera: Camera,
    bearing_deg: float,
    *,
    pitch_deg: float | None = None,
    distance_scale: float = 1.0,
) -> Camera:
    """Move a camera around its target's vertical axis, optionally steeper and further away."""

    offset = [camera.position[axis] - camera.target[axis] for axis in range(3)]
    ground = math.hypot(offset[0], offset[1])
    distance = math.sqrt(ground * ground + offset[2] * offset[2]) * distance_scale
    if ground <= 0 or distance <= 0:
        return camera
    heading = math.atan2(offset[1], offset[0]) + math.radians(bearing_deg)
    pitch = math.radians(pitch_deg) if pitch_deg is not None else math.atan2(offset[2], ground)
    position = (
        camera.target[0] + math.cos(heading) * math.cos(pitch) * distance,
        camera.target[1] + math.sin(heading) * math.cos(pitch) * distance,
        camera.target[2] + math.sin(pitch) * distance,
    )
    return camera.model_copy(update={"position": position})


def frame_buildings(camera: Camera, scene: CanonicalScene) -> Camera:
    """Keep the planned bearing and angle, but stand close enough to read the buildings.

    Every authored building counts, utility blocks included: a site plan's office drawn as a
    plain box arrives as one, and framing the shed alone cropped it out of the concept, which
    left the provider to invent the rest of the campus differently for each concept. Only
    buildings standing on the site count: one box left a hundred metres outside it stretched the
    frame until the site filled too little of it to pass the camera check, on every retry.
    """

    grounds = [
        element.bounding_box
        for element in scene.elements
        if element.semantic_role is SemanticRole.SITE_GROUND
    ]

    def on_site(element: SceneElement) -> bool:
        box = element.bounding_box
        x = (box.minimum[0] + box.maximum[0]) / 2
        y = (box.minimum[1] + box.maximum[1]) / 2
        return not grounds or any(
            ground.minimum[0] <= x <= ground.maximum[0]
            and ground.minimum[1] <= y <= ground.maximum[1]
            for ground in grounds
        )

    buildings = [
        element
        for element in scene.elements
        if element.semantic_role
        in {SemanticRole.MAIN_SHED, SemanticRole.OFFICE_BLOCK, SemanticRole.UTILITY_BLOCK}
        and on_site(element)
    ]
    if not buildings:
        return camera
    low = [min(item.bounding_box.minimum[axis] for item in buildings) for axis in range(3)]
    high = [max(item.bounding_box.maximum[axis] for item in buildings) for axis in range(3)]
    height = high[2] - low[2]
    target = ((low[0] + high[0]) / 2, (low[1] + high[1]) / 2, low[2] + height * 0.12)
    offset = [camera.position[axis] - camera.target[axis] for axis in range(3)]
    planned_distance = math.sqrt(sum(value * value for value in offset))
    if planned_distance <= 0:
        return camera
    direction = [value / planned_distance for value in offset]
    half_view = math.atan(camera.sensor_width_mm / 2 / camera.focal_length_mm)
    diagonal = math.hypot(high[0] - low[0], high[1] - low[1])
    fitted = CONCEPT_FRAME_MARGIN * diagonal / 2 / math.tan(half_view)
    distance = min(planned_distance, max(fitted, height * 4))
    position = (
        target[0] + direction[0] * distance,
        target[1] + direction[1] * distance,
        target[2] + direction[2] * distance,
    )
    return camera.model_copy(update={"position": position, "target": target})


def proposed_shots(settings: Settings, model_revision: str, design_revision: str) -> ViewSet:
    """The studio set for this design: the concept aerial, four more aerials, the entrance.

    The planner's standard set is two aerials and four eye-level views. Close views show the
    most conditioning render per pixel, and they were the ones that came back looking like CGI
    next to the concept; the studio keeps one, at the entrance, and photographs the rest from
    the air at the concept's own distance.
    """

    planned_path = _design_directory(settings, model_revision, design_revision) / "view_set.json"
    scene_path = _scene_path(settings, model_revision)
    if not planned_path.is_file() or not scene_path.is_file():
        raise FileNotFoundError("no planned cameras for this design")
    scene = CanonicalScene.model_validate_json(scene_path.read_text(encoding="utf-8"))
    planned = ViewSet.model_validate_json(planned_path.read_text(encoding="utf-8"))
    hero = studio_hero(settings, scene, scene_path, model_revision)
    aerials = (
        *(orbit(hero, bearing) for bearing in AERIAL_ORBIT_DEG),
        orbit(
            hero,
            MASTERPLAN_BEARING_DEG,
            pitch_deg=MASTERPLAN_PITCH_DEG,
            distance_scale=MASTERPLAN_DISTANCE_SCALE,
        ),
    )
    entrance = next(
        (camera for camera in planned.cameras if camera.role is ViewRole.CONTEXT),
        planned.cameras[-1],
    )
    cameras = (
        hero,
        *(
            camera.model_copy(update={"view_id": f"view-{index + 2:02d}", "role": ViewRole.DETAIL})
            for index, camera in enumerate(aerials)
        ),
        entrance.model_copy(
            update={"view_id": f"view-{len(aerials) + 2:02d}", "role": ViewRole.CONTEXT}
        ),
    )
    return planned.model_copy(update={"cameras": cameras})


class StartImageSet:
    """Generate the user's shots anchored to the concept image they chose."""

    def execute(
        self,
        settings: Settings,
        repository: JobRepository,
        *,
        concept_view_set_id: str,
        shots: tuple[ShotSpec, ...],
    ) -> tuple[GenerationJob, bool]:
        if not shots:
            raise InvalidModelError("choose at least one shot")
        if len(shots) > MAX_SHOTS:
            raise InvalidModelError(f"a set takes at most {MAX_SHOTS} shots besides the concept")
        concept = repository.get_by_view_set(concept_view_set_id)
        if concept.state is not WorkflowState.DESIGN_MASTER_REVIEW:
            raise InvalidModelError("the concept is not ready")
        concept_paths = _JobPaths.from_job(settings.artifact_dir, concept)
        concept_set = ViewSet.model_validate_json(concept_paths.view_set.read_text("utf-8"))
        hero = concept_set.cameras[0]
        hero_directory = concept_paths.generated_root / hero.view_id
        _refined(hero_directory)

        cameras = (
            hero,
            *(
                Camera(
                    view_id=f"view-{index + 2:02d}",
                    role=shot.role,
                    position=shot.position,
                    target=shot.target,
                    focal_length_mm=shot.focal_length_mm,
                    sensor_width_mm=shot.sensor_width_mm,
                    aspect_ratio=shot.aspect_ratio,
                )
                for index, shot in enumerate(shots)
            ),
        )
        digest = hashlib.sha256(
            json.dumps(
                [concept.view_set_id, *(camera.model_dump(mode="json") for camera in cameras)],
                sort_keys=True,
            ).encode()
        ).hexdigest()
        view_set = ViewSet(
            view_set_id=f"{concept.design_revision}-set-{digest[:10]}",
            design_revision=concept.design_revision,
            cameras=cameras,
        )
        created = CreateGenerationJob().execute(
            repository,
            project_id=concept.project_id,
            model_revision=concept.model_revision,
            design_revision=concept.design_revision,
            view_set=view_set,
            profile=concept.profile,
            render_profile=concept.render_profile,
            image_provider=concept.image_provider,
            reference_image_refs=concept.reference_image_refs,
            reference_roles=concept.reference_roles,
            style_pack_ref=concept.style_pack_ref,
        )
        job = created.job
        if created.created:
            paths = _JobPaths.from_job(settings.artifact_dir, job)
            target = paths.generated_root / hero.view_id
            shutil.copytree(hero_directory, target, dirs_exist_ok=True)
            master = str(_refined(target))
            atomic_write(
                paths.generated_root / "design_master_review.json",
                json.dumps(
                    {
                        "schema_version": "1.0.0",
                        "view_set_id": job.view_set_id,
                        "status": "approved",
                        "approved": True,
                        "approved_by": "concept_selection",
                        "concept_view_set_id": concept.view_set_id,
                        "approved_master_types": ["site", "facade"],
                        "master_view_id": hero.view_id,
                        "master_image_ref": master,
                        "master_view_ids": {"site": hero.view_id, "facade": hero.view_id},
                        "master_image_refs": {"site": master, "facade": master},
                    },
                    indent=2,
                ).encode()
                + b"\n",
            )
            job = job.transition(WorkflowState.RENDERING_PASSES)
            repository.save(job)
        return job, created.created


class FinalizeImageSet:
    """Compose the board and complete the set without stamping another brand on it."""

    def execute(
        self, settings: Settings, repository: JobRepository, view_set_id: str
    ) -> GenerationJob:
        job = repository.get_by_view_set(view_set_id)
        if job.state is WorkflowState.COMPLETED:
            return job
        if job.state is not WorkflowState.HUMAN_REVIEW:
            raise InvalidModelError("the images are not ready")
        paths = _JobPaths.from_job(settings.artifact_dir, job)
        board = ComposeViewSetBoard().execute(paths.generated_root, paths.board)
        qa_passed = False
        qa_path = paths.generated_root / "technical_qa.json"
        if qa_path.is_file():
            try:
                qa_passed = bool(json.loads(qa_path.read_text(encoding="utf-8")).get("passed"))
            except (OSError, ValueError):
                qa_passed = False
        atomic_write(
            paths.generated_root / "final_viewset_review.json",
            json.dumps(
                {
                    "schema_version": "1.0.0",
                    # Delivered by the person who chose the images; not a quality
                    # baseline, which requires an explicit approval of its own.
                    "status": "delivered",
                    "approved": False,
                    "view_set_id": job.view_set_id,
                    "technical_qa_passed": qa_passed,
                },
                indent=2,
            ).encode()
            + b"\n",
        )
        job = job.transition(WorkflowState.COMPOSING_BOARD)
        repository.save(job)
        refs = tuple(dict.fromkeys((*job.artifact_refs, str(board.board_path))))
        job = job.transition(WorkflowState.COMPLETED, artifact_refs=refs)
        repository.save(job)
        return job


class RegenerateView:
    """Generate one view again, anchored to the same concept image."""

    def execute(
        self,
        settings: Settings,
        repository: JobRepository,
        view_set_id: str,
        view_id: str,
        instruction: str = "",
    ) -> GenerationJob:
        job = repository.get_by_view_set(view_set_id)
        if job.state not in {WorkflowState.HUMAN_REVIEW, WorkflowState.COMPLETED}:
            raise InvalidModelError("the images are still being generated")
        paths = _JobPaths.from_job(settings.artifact_dir, job)
        view_set = ViewSet.model_validate_json(paths.view_set.read_text(encoding="utf-8"))
        if view_id not in {camera.view_id for camera in view_set.cameras}:
            raise FileNotFoundError("view not found in this set")
        if view_id == HERO_VIEW_ID:
            raise InvalidModelError("the concept image is the approved master; edit it instead")
        atomic_write(
            paths.generated_root / "manual_repair_request.json",
            json.dumps(
                {
                    "schema_version": "1.0.0",
                    "view_set_id": job.view_set_id,
                    "view_id": view_id,
                    "instruction": instruction.strip(),
                    "attempt": job.attempt + 1,
                },
                indent=2,
            ).encode()
            + b"\n",
        )
        job = job.transition(WorkflowState.REPAIRING)
        repository.save(job)
        return job
