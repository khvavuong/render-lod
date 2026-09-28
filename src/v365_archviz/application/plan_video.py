"""Create a cost-bounded motion plan from one approved six-view image set."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from v365_archviz.artifacts import atomic_write
from v365_archviz.config import Settings
from v365_archviz.domain.video import VideoPlan, VideoShot
from v365_archviz.domain.workflow import ViewSet
from v365_archviz.errors import InvalidModelError

MOTION_PROMPTS = {
    "overall": (
        "A restrained cinematic drone push forward with a very slight descent over the complete "
        "industrial campus. One or two existing vehicles move slowly only along visible authored "
        "roads. Tree foliage moves almost imperceptibly in a light breeze."
    ),
    "context": (
        "A slow, stable lateral drone slide revealing the site relationship and approach roads. "
        "Existing vehicles move subtly along visible roads and foliage has minimal natural motion."
    ),
    "hero": (
        "A slow, stable dolly forward through the factory corridor at low architectural-camera "
        "height. Existing adults walk naturally and one existing logistics vehicle moves slowly."
    ),
    "detail": (
        "A smooth, slow tracking move parallel to the long factory facade, keeping the complete "
        "roof edge and elevation readable. Only subtle vehicle and foliage motion."
    ),
    "office_hero": (
        "A restrained forward-and-sideways camera approach toward the access frontage and gate. "
        "One existing vehicle moves slowly through the visible circulation route."
    ),
    "loading_detail": (
        "A gentle human-eye-level stabilized walk forward through the open-air exterior authored "
        "circulation space, always outside the building envelope. Existing adults and vehicles "
        "move slowly and naturally without approaching the camera."
    ),
    "custom": (
        "A slow, stable cinematic push forward from this exact viewpoint, keeping the framed "
        "architecture readable. Existing vehicles and people move subtly; foliage barely moves."
    ),
}

PRESERVATION_PROMPT = (
    "Animate this exact approved architectural still. Treat the input image as immutable design "
    "authority: preserve the camera direction, factory count, massing, dimensions, longitudinal "
    "gable roofs, facade modules, gates, guardhouses, fences, roads, curbs, landscape boundaries, "
    "surrounding context, materials, colors, daylight and every object position. Motion must be "
    "slow, physically plausible and presentation-grade. Keep straight lines rigid and temporal "
    "details stable. No cuts, no transition, no text, no logo, no soundtrack and no dialogue. "
)

NEGATIVE_PROMPT = (
    "architectural deformation, geometry drift, changing building count, new building, removed "
    "building, roof deformation, transverse roof, flat roof, facade redesign, changing doors, "
    "changing windows, moving gate, missing fence, altered road, altered curb, altered landscape, "
    "camera shake, fast motion, orbit, crash zoom, time lapse, object morphing, flicker, shimmer, "
    "rubber walls, bent lines, duplicated vehicle, disappearing vehicle, crowd, surreal color, "
    "purple facade, blue facade, rain, night, subtitles, watermark, logo"
)


@dataclass(frozen=True, slots=True)
class VideoPlanArtifacts:
    plan: VideoPlan
    plan_path: Path


def _object(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise InvalidModelError(f"{name} must be a JSON object")
    return value


class PlanVideo:
    def execute(
        self,
        generated_root: Path,
        view_set_path: Path,
        output_root: Path,
        settings: Settings,
    ) -> VideoPlanArtifacts:
        manifest_path = generated_root / "viewset_generation_manifest.json"
        if not manifest_path.is_file():
            raise InvalidModelError(f"missing generated view-set manifest: {manifest_path}")
        manifest = _object(json.loads(manifest_path.read_text(encoding="utf-8")), "manifest")
        view_set = ViewSet.model_validate_json(view_set_path.read_text(encoding="utf-8"))
        design_revision = manifest.get("design_revision")
        if design_revision != view_set.design_revision:
            raise InvalidModelError("generated images and view set use different design revisions")

        shot_inputs: list[tuple[str, str, Path, str]] = []
        for index, camera in enumerate(view_set.cameras, start=1):
            view_root = generated_root / camera.view_id
            provider_sources = sorted(view_root.glob("provider_source.*"))
            refined = sorted(view_root.glob("refined.*"))
            if not settings.brand_watermark and len(refined) == 1:
                # Unbranded deliveries keep `refined` clean, and it is the only file an edit
                # rewrites; the raw provider image would bring an edited view back unedited.
                source = refined[0]
            else:
                source = (
                    provider_sources[0]
                    if len(provider_sources) == 1
                    else view_root / "refined.jpg"
                )
            if not source.is_file():
                raise InvalidModelError(f"missing approved source image: {source}")
            role = camera.role.value
            try:
                motion = MOTION_PROMPTS[role]
            except KeyError as exc:
                raise InvalidModelError(f"unsupported video view role: {role}") from exc
            shot_inputs.append((f"shot-{index:02d}", camera.view_id, source, motion))

        identity = hashlib.sha256()
        identity.update(manifest_path.read_bytes())
        identity.update(settings.veo_model.encode())
        identity.update(str(settings.veo_duration_seconds).encode())
        identity.update(settings.veo_resolution.encode())
        for _, _, source, motion in shot_inputs:
            identity.update(source.read_bytes())
            identity.update(motion.encode())
        plan_id = f"video-{identity.hexdigest()[:16]}"

        shots = tuple(
            VideoShot(
                shot_id=shot_id,
                view_id=view_id,
                source_image_ref=str(source.resolve()),
                prompt=PRESERVATION_PROMPT + motion,
                negative_prompt=NEGATIVE_PROMPT,
                duration_seconds=settings.veo_duration_seconds,
                aspect_ratio="16:9",
                resolution=settings.veo_resolution,
                seed=int(hashlib.sha256(f"{plan_id}:{shot_id}".encode()).hexdigest()[:8], 16),
            )
            for shot_id, view_id, source, motion in shot_inputs
        )
        plan = VideoPlan(
            plan_id=plan_id,
            project_id=str(manifest.get("project_id", "unknown-project")),
            model_revision=str(manifest.get("model_revision", "unknown-model")),
            design_revision=str(design_revision),
            view_set_id=view_set.view_set_id,
            provider_model=settings.veo_model,
            price_per_second_usd=settings.veo_price_per_second_usd,
            budget_usd=settings.video_budget_usd,
            shots=shots,
        )
        plan_directory = output_root / plan.model_revision / plan.design_revision / plan.plan_id
        plan_path = plan_directory / "video_plan.json"
        atomic_write(
            plan_path,
            plan.model_dump_json(indent=2, exclude_computed_fields=True).encode() + b"\n",
        )
        return VideoPlanArtifacts(plan=plan, plan_path=plan_path)
