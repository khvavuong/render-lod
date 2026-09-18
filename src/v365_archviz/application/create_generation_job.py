"""Create one idempotent durable job for an immutable view set."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from v365_archviz.domain.jobs import GenerationJob
from v365_archviz.domain.style_pack import StylePack
from v365_archviz.domain.workflow import GenerationProfile, RenderProfile, ViewSet, WorkflowState
from v365_archviz.providers.contracts import JobRepository


@dataclass(frozen=True, slots=True)
class CreatedGenerationJob:
    job: GenerationJob
    created: bool


def generation_idempotency_key(
    project_id: str,
    model_revision: str,
    design_revision: str,
    view_set_id: str,
    profile: GenerationProfile,
    render_profile: RenderProfile,
    image_provider: str = "gemini",
    reference_hashes: tuple[str, ...] = (),
    style_hash: str = "",
) -> str:
    payload = "\n".join(
        (
            project_id,
            model_revision,
            design_revision,
            view_set_id,
            profile.value,
            render_profile.value,
            image_provider,
            *reference_hashes,
            *((style_hash,) if style_hash else ()),
        )
    ).encode()
    return hashlib.sha256(payload).hexdigest()


class CreateGenerationJob:
    def execute(
        self,
        repository: JobRepository,
        *,
        project_id: str,
        model_revision: str,
        design_revision: str,
        view_set: ViewSet,
        profile: GenerationProfile,
        render_profile: RenderProfile = RenderProfile.STANDARD_EEVEE,
        image_provider: str = "gemini",
        reference_image_refs: tuple[str, ...] = (),
        reference_roles: tuple[str, ...] = (),
        style_pack_ref: str | None = None,
        proposal_snapshot: str | None = None,
    ) -> CreatedGenerationJob:
        if proposal_snapshot:
            if profile is not GenerationProfile.MARKETING_HERO or image_provider != "gemini":
                raise ValueError("Proposal policy requires marketing/Gemini")
            spec = json.loads(proposal_snapshot)
            if spec.get("version") != "reference-led-proposal-v1":
                raise ValueError("Unknown proposal version")
        if style_pack_ref is None and profile is GenerationProfile.MARKETING_HERO:
            style_pack_ref = str(
                Path(__file__).resolve().parents[3]
                / "resource/style_packs/marketing_photoreal.json"
            )
        snapshot = StylePack.load(Path(style_pack_ref)).to_json() if style_pack_ref else None
        key = generation_idempotency_key(
            project_id,
            model_revision,
            design_revision,
            view_set.view_set_id,
            profile,
            render_profile,
            image_provider,
            tuple(
                hashlib.sha256(Path(value).read_bytes() + role.encode()).hexdigest()
                for value, role in zip(reference_image_refs, reference_roles, strict=True)
            ),
            hashlib.sha256(
                (snapshot or "").encode() + (proposal_snapshot or "").encode()
            ).hexdigest()
            if snapshot or proposal_snapshot
            else "",
        )
        candidate = GenerationJob.create(
            job_id=f"job-{key[:16]}",
            idempotency_key=key,
            project_id=project_id,
            model_revision=model_revision,
            design_revision=design_revision,
            view_set_id=f"{view_set.view_set_id}-{key[:8]}" if snapshot else view_set.view_set_id,
            profile=profile,
            render_profile=render_profile,
            image_provider=image_provider,
            reference_image_refs=reference_image_refs,
            reference_roles=reference_roles,
            style_pack_ref=style_pack_ref,
            style_pack_snapshot=snapshot,
            output_namespace=f"job-{key[:16]}" if snapshot else None,
            view_set_snapshot=(
                view_set.model_copy(
                    update={"view_set_id": f"{view_set.view_set_id}-{key[:8]}"}
                ).model_dump_json(indent=2)
                if snapshot
                else None
            ),
            initial_state=WorkflowState.PLANNING_CAMERAS,
        )
        if proposal_snapshot:
            candidate = candidate.model_copy(
                update={
                    "generation_policy": "reference-led-proposal-v1",
                    "proposal_snapshot": proposal_snapshot,
                }
            )
        job, created = repository.create_or_get(candidate)
        return CreatedGenerationJob(job=job, created=created)
