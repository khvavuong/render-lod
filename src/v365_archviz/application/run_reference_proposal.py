"""Bounded main-flow proposal pilot. Outputs are concepts, never certified deliveries."""

from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path

from PIL import Image

from v365_archviz.application.reference_led_input import VERSION
from v365_archviz.artifacts import atomic_write
from v365_archviz.domain.workflow import ViewRole, WorkflowState
from v365_archviz.errors import V365Error
from v365_archviz.providers.contracts import ViewConditioningInput
from v365_archviz.providers.image_factory import create_image_renderer


def write_json(path: Path, data: dict) -> None:
    atomic_write(path, json.dumps(data, ensure_ascii=False, indent=2).encode() + b"\n")


def run_proposal(repository, job, settings, paths, view_set):
    if job.state not in {WorkflowState.RENDERING_PASSES, WorkflowState.GENERATING_VIEWSET}:
        return job
    spec = json.loads(job.proposal_snapshot or "{}")
    if spec.get("version") != VERSION or job.image_provider != "gemini":
        raise V365Error("Invalid proposal policy snapshot")
    references = spec["references"]
    if spec.get("max_generation_calls") != 2:
        raise V365Error("Proposal call budget must be exactly two")
    if hashlib.sha256(paths.scene.read_bytes()).hexdigest() != spec["source_sha256"]:
        raise V365Error("Proposal source changed; create a new job")
    for ref in references:
        if hashlib.sha256(Path(ref["path"]).read_bytes()).hexdigest() != ref["sha256"]:
            raise V365Error("Proposal reference changed; create a new job")
    targets = {}
    for role, purpose in ((ViewRole.OVERALL, "site"), (ViewRole.OFFICE_HERO, "facade")):
        candidates = [camera for camera in view_set.cameras if camera.role is role]
        if not candidates:
            raise V365Error(f"No proposal purpose slot: {role.value}")
        targets[purpose] = candidates[0]
    # These camera records supply role/slot only; no image or pose is sent to the model.
    if job.state is WorkflowState.RENDERING_PASSES:
        job = job.transition(WorkflowState.GENERATING_VIEWSET)
        repository.save(job)
    master_refs, hashes = {}, {}
    with create_image_renderer(settings, job.image_provider) as renderer:
        for purpose, camera in targets.items():
            root = paths.generated_root / camera.view_id
            prompt = spec["prompts"][camera.role.value]
            inputs = {
                "policy": VERSION,
                "prompt": prompt,
                "references": references,
                "model": spec["model"],
                "image_size": "2K",
                "aspect_ratio": "16:9",
            }
            signature = hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()
            manifest_path = root / "generation_manifest.json"
            if manifest_path.is_file():
                cached = json.loads(manifest_path.read_text(encoding="utf-8"))
                if cached.get("input_sha256") != signature or cached.get("status") != "complete":
                    raise V365Error("Uncertain/stale proposal call; no automatic retry")
                output = Path(cached["output_ref"])
                if hashlib.sha256(output.read_bytes()).hexdigest() != cached["output_sha256"]:
                    raise V365Error("Proposal output changed")
            else:
                root.mkdir(parents=True, exist_ok=True)
                try:
                    reservation = os.open(
                        root / "call_reserved", os.O_CREAT | os.O_EXCL | os.O_WRONLY
                    )
                except FileExistsError as exc:
                    raise V365Error("Proposal call already reserved; no retry") from exc
                os.close(reservation)
                # A persisted reservation survives exceptions/process death. At most two calls/job.
                write_json(
                    manifest_path,
                    {
                        "status": "in_flight",
                        "input_sha256": signature,
                        "inputs": inputs,
                        "output_stage": "design_proposal",
                    },
                )
                unused = root / "not_sent.png"
                image = renderer.generate(
                    ViewConditioningInput(
                        view_id=camera.view_id,
                        base_rgb=unused,
                        depth=unused,
                        instance_id=unused,
                        semantic=unused,
                        edges=unused,
                        prompt=prompt,
                        image_size="2K",
                        generation_policy=VERSION,
                        role=camera.role.value,
                        reference_images=tuple(Path(ref["path"]) for ref in references),
                        reference_roles=tuple(ref["role"] for ref in references),
                        reference_instructions=tuple(ref["instruction"] for ref in references),
                        provider_model=spec["model"],
                    )
                )
                if image.media_type not in {"image/png", "image/jpeg", "image/webp"}:
                    raise V365Error("Unsupported proposal image type")
                with Image.open(io.BytesIO(image.content)) as decoded:
                    decoded.verify()
                suffix = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}
                output = root / ("refined" + suffix[image.media_type])
                atomic_write(output, image.content)
                write_json(
                    manifest_path,
                    {
                        "status": "complete",
                        "input_sha256": signature,
                        "inputs": inputs,
                        "output_ref": str(output),
                        "output_sha256": hashlib.sha256(image.content).hexdigest(),
                        "provider_request_id": image.provider_request_id,
                        "output_stage": "design_proposal",
                        "geometry_verified": False,
                    },
                )
            master_refs[purpose] = str(output)
            hashes[purpose] = hashlib.sha256(output.read_bytes()).hexdigest()
    review_path = paths.generated_root / "design_master_review.json"
    write_json(
        review_path,
        {
            "view_set_id": job.view_set_id,
            "generation_policy": VERSION,
            "status": "proposal_review",
            "approved": False,
            "master_view_id": targets["site"].view_id,
            "master_view_ids": {purpose: camera.view_id for purpose, camera in targets.items()},
            "master_image_ref": master_refs["site"],
            "master_image_refs": master_refs,
            "master_hashes": hashes,
            "geometry_verified": False,
            "delivery_approved": False,
            "consistency": "unknown: independently generated design proposals",
            "next_stage": "select_concept_then_register_design_and_shots",
        },
    )
    job = job.transition(WorkflowState.DESIGN_MASTER_REVIEW, artifact_refs=(str(review_path),))
    repository.save(job)
    return job
