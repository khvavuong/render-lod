"""Registered design branches, bounded generation and evidence-scoped review."""

from __future__ import annotations

import hashlib
import io
import json
import os
import time
from pathlib import Path
from typing import Literal

from PIL import Image
from pydantic import BaseModel, ConfigDict, Field

from v365_archviz.application.reference_led_input import BRIEF, REGIONAL_CONTEXT, VERSION
from v365_archviz.application.run_reference_proposal import write_json
from v365_archviz.artifacts import atomic_write
from v365_archviz.domain.workflow import ViewRole, WorkflowState
from v365_archviz.errors import V365Error
from v365_archviz.providers.contracts import ViewConditioningInput
from v365_archviz.providers.image_factory import create_image_renderer

REGISTERED_VERSION = "reference-led-registered-v1"


class ApprovedRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field: str = Field(min_length=1, max_length=80)
    value: str = Field(min_length=1, max_length=2000)
    evidence_ref: str = Field(min_length=1, max_length=500)
    scope: str = Field(min_length=1, max_length=200)


class RegisterDesignRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    anchor: Literal["site", "facade"]
    reviewer: str = Field(min_length=1, max_length=120)
    requirements: list[ApprovedRequirement] = Field(default_factory=list, max_length=30)
    design_notes: str = Field(default="", max_length=4000)


class SelectShotsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    candidate_ids: list[str] = Field(min_length=6, max_length=6)


class DeliveryReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reviewer: str = Field(min_length=1, max_length=120)
    decision: Literal["approve", "reject"]
    realism: bool
    architecture: bool
    consistency: bool
    vietnam_context: bool
    source_requirements: bool
    camera_fidelity: bool
    evidence_notes: str = Field(min_length=20, max_length=6000)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def digest(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def verify_inputs(job, paths):
    spec = json.loads(job.proposal_snapshot or "{}")
    if spec.get("version") != VERSION or sha(paths.scene) != spec["source_sha256"]:
        raise V365Error("Source snapshot changed")
    if any(sha(ref["path"]) != ref["sha256"] for ref in spec["references"]):
        raise V365Error("Reference snapshot changed")
    return spec


def register_design(job, paths, request: RegisterDesignRequest):
    if job.generation_policy != VERSION or job.state is not WorkflowState.DESIGN_MASTER_REVIEW:
        raise V365Error("Only proposal-review jobs can register a design")
    spec = verify_inputs(job, paths)
    review = json.loads((paths.generated_root / "design_master_review.json").read_text())
    anchor = review["master_image_refs"][request.anchor]
    if sha(anchor) != review["master_hashes"][request.anchor]:
        raise V365Error("Selected proposal changed")
    if len({r.field for r in request.requirements}) != len(request.requirements):
        raise V365Error("Duplicate requirement fields")
    fields = [
        {
            "field": "source_envelopes",
            "value": spec.get("envelopes", []),
            "provenance": "source",
            "evidence_ref": str(paths.scene),
            "approval_ref": None,
            "scope": "measured placement/footprint/height, not facade programme",
        },
        {
            "field": "visual_design_identity",
            "value": review["master_hashes"][request.anchor],
            "provenance": "client_approved",
            "evidence_ref": anchor,
            "approval_ref": request.reviewer,
            "scope": "visible architecture only",
        },
    ]
    fields.extend(
        {**r.model_dump(), "provenance": "client_approved", "approval_ref": request.reviewer}
        for r in request.requirements
    )
    core = {
        "policy": REGISTERED_VERSION,
        "parent_job_id": job.job_id,
        "source_sha256": spec["source_sha256"],
        "anchor_ref": anchor,
        "anchor_sha256": sha(anchor),
        "requirements": fields,
        "design_notes": request.design_notes,
        "reviewer": request.reviewer,
    }
    family = {
        **core,
        "master_family_id": "family-" + digest(core)[:20],
        "unknown": ["unseen facades", "unapproved programme", "output source fidelity"],
        "max_generation_calls": 6,
        "geometry_verified": False,
    }
    path = paths.generated_root / "registered_design.json"
    if path.exists():
        if json.loads(path.read_text()) != family:
            raise V365Error(
                "Design branch is immutable; create a new proposal job for another variant"
            )
    else:
        write_json(path, family)
    return family


def select_shots(job, paths, request: SelectShotsRequest):
    spec = verify_inputs(job, paths)
    ranking = json.loads((paths.generated_root / "shots/ranking.json").read_text())
    rows = {r["candidate_id"]: r for r in ranking["candidates"]}
    if len(set(request.candidate_ids)) != 6 or any(c not in rows for c in request.candidate_ids):
        raise V365Error("Choose six distinct existing candidates")
    selected = [rows[c] for c in request.candidate_ids]
    if {r["camera"]["role"] for r in selected} != {r.value for r in ViewRole}:
        raise V365Error("Choose one camera for each purpose")
    if any(not r["measurement"]["feasible"] or r["score"] <= 0 for r in selected):
        raise V365Error("Selected camera failed source composition preflight")
    family = json.loads((paths.generated_root / "registered_design.json").read_text())
    selected.sort(key=lambda r: r["camera"]["role"])
    result = {
        "master_family_id": family["master_family_id"],
        "shots": [
            {**r, "view_id": f"view-{i:02d}", "evidence_sha256": sha(r["evidence_ref"])}
            for i, r in enumerate(selected, 1)
        ],
        "output_camera_verified": False,
    }
    for shot in result["shots"]:
        shot["prompt"] = registered_prompt(spec, family, shot)
        shot["references"] = [
            *spec["references"],
            {
                "path": family["anchor_ref"],
                "sha256": family["anchor_sha256"],
                "role": "approved_design_anchor",
                "instruction": "Selected design, not camera.",
            },
            {
                "path": shot["evidence_ref"],
                "sha256": shot["evidence_sha256"],
                "role": "source_geometry_evidence",
                "instruction": "Source frame, not facade programme.",
            },
        ]
    path = paths.generated_root / "selected_shots.json"
    if (
        path.exists()
        and (paths.generated_root / "registered").exists()
        and json.loads(path.read_text()) != result
    ):
        raise V365Error("Cannot change shots after generation starts; create another branch")
    write_json(path, result)
    return result


PURPOSES = {
    "overall": "An informative oblique aerial explaining the whole project and circulation.",
    "detail": "A reverse aerial showing other visible sides without changing the design.",
    "context": "A site-context photograph explaining arrival and the relationship to surroundings.",
    "hero": "A human-scale industrial frontage photograph with warm directional daylight.",
    "office_hero": "A human-scale office/entrance architectural photograph; partial view is valid.",
    "loading_detail": "An operations photograph. Do not invent raised docks or new openings.",
}


def registered_prompt(spec, family, shot):
    return (
        BRIEF
        + "\n\nREGIONAL CONTEXT\n"
        + REGIONAL_CONTEXT
        + "\n\nREGISTERED DESIGN\nContinue the selected design, not a new architectural option. "
        "Preserve visible material identity, office proportions and facade language in the anchor. "
        "Do not transplant its camera. Unseen surfaces are unresolved proposals, not source facts. "
        "Do not fabricate programme for a missing view. Partial shots cannot prove campus counts.\n"
        "The selected anchor takes priority over architectural motifs in the original references. "
        "Authority is field-specific: source envelopes govern massing/placement; the selected "
        "geometry image governs camera and framing; the anchor governs visible architectural "
        "identity only. Never reuse the anchor's aerial viewpoint for a ground-level source frame. "
        + json.dumps(family, ensure_ascii=False)
        + "\n\nSOURCE ENVELOPES\n"
        + json.dumps(spec.get("envelopes", []))
        + "\n\nUSER BRIEF\n"
        + spec.get("brief", "")
        + "\n\nSHOT PURPOSE\n"
        + PURPOSES[shot["camera"]["role"]]
        + "\n\nSELECTED SOURCE CAMERA\n"
        + json.dumps(shot["camera"])
        + "\nUse the source-only geometry image for relative placement, massing and framing. "
        "It does not prescribe facade styling, openings or a generated programme. "
        "Image conditioning is guidance, not a hard geometric control."
        " Keep the selected source viewpoint and visible face relationships. Do not raise the "
        "camera to reveal roofs when the source image is at eye level. Do not substitute a "
        "whole-campus aerial for a partial office or operations photograph."
    )


def generate_registered(repository, job, settings, paths):
    if job.state is WorkflowState.VALIDATING:
        verify_inputs(job, paths)
        qa = json.loads((paths.generated_root / "registered/stage_qa.json").read_text())
        for view_id, expected in qa["output_hashes"].items():
            files = list((paths.generated_root / "registered" / view_id).glob("refined.*"))
            if len(files) != 1 or sha(files[0]) != expected:
                raise V365Error("Registered checkpoint output changed")
        if len(qa["output_hashes"]) != 6:
            raise V365Error("Incomplete registered validation checkpoint")
        job = job.transition(WorkflowState.HUMAN_REVIEW)
        repository.save(job)
        return job
    if job.state is not WorkflowState.GENERATING_VIEWSET:
        return job
    spec = verify_inputs(job, paths)
    family = json.loads((paths.generated_root / "registered_design.json").read_text())
    selected = json.loads((paths.generated_root / "selected_shots.json").read_text())
    if (
        selected["master_family_id"] != family["master_family_id"]
        or sha(family["anchor_ref"]) != family["anchor_sha256"]
    ):
        raise V365Error("Master family lineage changed")
    if len(selected["shots"]) != 6 or family["max_generation_calls"] != 6:
        raise V365Error("Invalid registered generation budget")
    for shot in selected["shots"]:
        if any(sha(ref["path"]) != ref["sha256"] for ref in shot["references"]):
            raise V365Error("Registered preflight reference changed")
    root = paths.generated_root / "registered"
    hashes, inputs = {}, []
    with create_image_renderer(settings, job.image_provider) as renderer:
        for shot in selected["shots"]:
            if sha(shot["evidence_ref"]) != shot["evidence_sha256"]:
                raise V365Error("Selected shot evidence changed")
            prompt = shot["prompt"]
            refs = shot["references"]
            if any(sha(r["path"]) != r["sha256"] for r in refs):
                raise V365Error("Frozen registered reference changed")
            data = {
                "policy": REGISTERED_VERSION,
                "family_id": family["master_family_id"],
                "prompt": prompt,
                "references": refs,
                "model": spec["model"],
                "image_size": "2K",
                "aspect_ratio": "16:9",
            }
            folder = root / shot["view_id"]
            folder.mkdir(parents=True, exist_ok=True)
            manifest = folder / "generation_manifest.json"
            if manifest.exists():
                cached = json.loads(manifest.read_text())
                if cached.get("status") != "complete" or cached["input_sha256"] != digest(data):
                    raise V365Error("Uncertain/stale registered call; no retry")
                output = Path(cached["output_ref"])
                if sha(output) != cached["output_sha256"]:
                    raise V365Error("Registered image changed")
            else:
                try:
                    handle = os.open(folder / "call_reserved", os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                except FileExistsError as exc:
                    raise V365Error("Registered call already reserved; no automatic retry") from exc
                os.close(handle)
                write_json(
                    manifest, {"status": "in_flight", "input_sha256": digest(data), "inputs": data}
                )
                unused = folder / "not_sent.png"
                started = time.monotonic()
                image = renderer.generate(
                    ViewConditioningInput(
                        view_id=shot["view_id"],
                        role=shot["camera"]["role"],
                        base_rgb=unused,
                        depth=unused,
                        instance_id=unused,
                        semantic=unused,
                        edges=unused,
                        prompt=prompt,
                        generation_policy=REGISTERED_VERSION,
                        image_size="2K",
                        reference_images=tuple(Path(r["path"]) for r in refs),
                        reference_roles=tuple(r["role"] for r in refs),
                        reference_instructions=tuple(r["instruction"] for r in refs),
                        provider_model=spec["model"],
                    )
                )
                suffix = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}.get(
                    image.media_type
                )
                if not suffix:
                    raise V365Error("Unsupported registered image type")
                with Image.open(io.BytesIO(image.content)) as decoded:
                    decoded.verify()
                output = folder / ("refined" + suffix)
                atomic_write(output, image.content)
                write_json(
                    manifest,
                    {
                        "status": "complete",
                        "input_sha256": digest(data),
                        "inputs": data,
                        "output_ref": str(output),
                        "output_sha256": sha(output),
                        "provider_request_id": image.provider_request_id,
                        "latency_ms": round((time.monotonic() - started) * 1000),
                    },
                )
            hashes[shot["view_id"]] = sha(output)
            inputs.append(digest(data))
    write_json(
        root / "stage_qa.json",
        {
            "view_set_id": job.view_set_id,
            "master_family_id": family["master_family_id"],
            "family_sha256": sha(paths.generated_root / "registered_design.json"),
            "selected_shots_sha256": sha(paths.generated_root / "selected_shots.json"),
            "output_hashes": hashes,
            "input_signatures": inputs,
            "artifact_integrity": "pass",
            "architecture": "unknown",
            "realism": "unknown",
            "vietnam_context": "unknown",
            "source_fidelity": "unknown",
            "camera_fidelity": "unknown",
            "consistency": "unknown",
            "delivery_approved": False,
            "geometry_certified": False,
            "review_scope": "Partial shots cannot verify whole-campus counts or unseen facades",
        },
    )
    job = job.transition(WorkflowState.VALIDATING)
    repository.save(job)
    job = job.transition(WorkflowState.HUMAN_REVIEW)
    repository.save(job)
    return job


def review_delivery(job, paths, request: DeliveryReviewRequest):
    if job.state is not WorkflowState.HUMAN_REVIEW:
        raise V365Error("Registered set must finish before review")
    verify_inputs(job, paths)
    root = paths.generated_root / "registered"
    qa = json.loads((root / "stage_qa.json").read_text())
    if (
        sha(paths.generated_root / "registered_design.json") != qa["family_sha256"]
        or sha(paths.generated_root / "selected_shots.json") != qa["selected_shots_sha256"]
    ):
        raise V365Error("Review lineage changed")
    family = json.loads((paths.generated_root / "registered_design.json").read_text())
    if sha(family["anchor_ref"]) != family["anchor_sha256"]:
        raise V365Error("Reviewed anchor changed")
    if len(qa["output_hashes"]) != 6:
        raise V365Error("Incomplete registered set")
    for view_id, expected in qa["output_hashes"].items():
        files = list((root / view_id).glob("refined.*"))
        if len(files) != 1 or sha(files[0]) != expected:
            raise V365Error("Reviewed output changed")
    passed = all(
        getattr(request, key)
        for key in (
            "realism",
            "architecture",
            "consistency",
            "vietnam_context",
            "source_requirements",
            "camera_fidelity",
        )
    )
    if request.decision == "approve" and not passed:
        raise V365Error("Delivery approval requires all human review checks; unknown is not pass")
    result = {
        **request.model_dump(),
        "view_set_id": job.view_set_id,
        "master_family_id": qa["master_family_id"],
        "output_hashes": qa["output_hashes"],
        "qa_sha256": sha(root / "stage_qa.json"),
        "geometry_certified": False,
        "status": "reviewed_marketing_delivery" if request.decision == "approve" else "rejected",
        "delivery_approved": request.decision == "approve",
    }
    write_json(root / "delivery_review.json", result)
    return result
