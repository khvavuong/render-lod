"""Source-only camera search and previews. Scores are composition advice, not AI fidelity."""

from __future__ import annotations

import json
import math
from dataclasses import asdict
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageOps

from v365_archviz.application.camera_candidates import (
    ROLE_OBJECTIVES,
    CandidateScore,
    propose_candidates,
    score_candidate,
    select_view_set,
)
from v365_archviz.application.reference_led_input import source_envelopes
from v365_archviz.application.run_reference_proposal import write_json
from v365_archviz.artifacts import atomic_write
from v365_archviz.domain.photography_pack import PhotographyPack
from v365_archviz.domain.workflow import PLANNED_ROLES, Camera, RenderProfile, ViewRole, ViewSet
from v365_archviz.errors import V365Error
from v365_archviz.providers.docker_conditioning import DockerConditioningRenderer


def search_shots(paths, job):
    scene = json.loads(paths.scene.read_text(encoding="utf-8"))
    source_envelopes(scene)  # Reject unknown classification, do not fabricate buildings.
    focus = [e for e in scene["elements"] if e["semantic_role"] in {"main_shed", "office_block"}]
    pack = PhotographyPack.load(Path("resource/photography_packs/documentary_industrial.json"))
    root = paths.generated_root / "shots"
    if (root / "ranking.json").exists():
        old = json.loads((root / "ranking.json").read_text())
        if old.get("search_version") == "source-eye-height-v3":
            raise V365Error("Shot search already exists; choose from this revision")
        if (paths.generated_root / "selected_shots.json").exists():
            raise V365Error("Selected shots are immutable; create a new branch")
        write_json(root / "history/ranking-v1.json", old)
    root.mkdir(parents=True, exist_ok=True)
    candidates = []
    for role in PLANNED_ROLES:
        elements = focus
        if role in {ViewRole.OFFICE_HERO, ViewRole.LOADING_DETAIL, ViewRole.HERO}:
            preferred = "office_block" if role is ViewRole.OFFICE_HERO else "main_shed"
            elements = [e for e in focus if e["semantic_role"] == preferred]
            if not elements and role is ViewRole.OFFICE_HERO:
                elements = [e for e in scene["elements"] if e["semantic_role"] == "main_entrance"]
            elements = elements or focus
            elements = [
                max(
                    elements,
                    key=lambda e: math.prod(
                        e["bounding_box"]["maximum"][a] - e["bounding_box"]["minimum"][a]
                        for a in range(3)
                    ),
                )
            ]
        low = tuple(min(e["bounding_box"]["minimum"][a] for e in elements) for a in range(3))
        high = tuple(max(e["bounding_box"]["maximum"][a] for e in elements) for a in range(3))
        target = (
            (low[0] + high[0]) / 2,
            (low[1] + high[1]) / 2,
            low[2] + (high[2] - low[2]) * 0.35,
        )
        candidates.extend(
            propose_candidates(
                role,
                pack.framing_for(role),
                (low, high),
                target,
                distance_factors=(1.0,),
                elevation_offsets=(0.0,),
                respect_eye_height=True,
            )
        )
    cameras = tuple(
        Camera(
            view_id=f"candidate-{i:02d}",
            role=c.role,
            position=c.position,
            target=c.target,
            focal_length_mm=c.focal_length_mm,
            sensor_width_mm=36,
            aspect_ratio="16:9",
        )
        for i, c in enumerate(candidates, 1)
    )
    view_set = ViewSet(
        view_set_id=job.view_set_id + "-candidates",
        design_revision=job.design_revision,
        cameras=cameras,
    )
    candidate_file = root / "candidate_view_set.json"
    atomic_write(candidate_file, view_set.model_dump_json(indent=2).encode())
    render_root = root / "renders"
    pending = []
    for camera in cameras:
        old_camera = render_root / camera.view_id / "camera.json"
        if (
            not old_camera.exists()
            or json.loads(old_camera.read_text()) != camera.model_dump(mode="json")
            or not (render_root / camera.view_id / "base_rgb.png").exists()
        ):
            pending.append(camera)
    if pending:
        pending_file = root / "pending_view_set.json"
        atomic_write(
            pending_file,
            view_set.model_copy(update={"cameras": tuple(pending)}).model_dump_json().encode(),
        )
        DockerConditioningRenderer().execute(
            paths.scene,
            paths.design_dna,
            pending_file,
            render_root,
            RenderProfile.PREVIEW_FAST,
            facade_mode="envelope_only",
            camera_scoring=True,
        )
    rows, ranked = [], {}
    contact = Image.new("RGB", (4 * 384, math.ceil(len(candidates) / 4) * 240), "#202630")
    draw = ImageDraw.Draw(contact)
    subject_roles = {"main_shed", "office_block", "roof", "primary_facade", "facade_secondary"}
    for i, (candidate, camera) in enumerate(zip(candidates, cameras, strict=True)):
        folder = render_root / camera.view_id
        palette = json.loads((folder / "semantic_id_manifest.json").read_text())["roles"]
        with Image.open(folder / "semantic.png") as image:
            pixels = np.asarray(image.convert("RGB"), dtype=np.int16)
        shares = {
            entry["semantic_role"]: float(
                np.mean(np.abs(pixels - np.array(entry["srgb8"])).max(axis=2) < 20)
            )
            for entry in palette
        }
        subject = sum(v for k, v in shares.items() if k in subject_roles)
        collision = any(
            all(
                e["bounding_box"]["minimum"][a]
                <= candidate.position[a]
                <= e["bounding_box"]["maximum"][a]
                for a in range(3)
            )
            for e in scene["elements"]
            if e["semantic_role"] in {"main_shed", "office_block", "utility_block"}
        )
        target_role = "main_shed"
        if camera.role is ViewRole.OFFICE_HERO:
            target_role = (
                "office_block"
                if any(e["semantic_role"] == "office_block" for e in focus)
                else "main_entrance"
            )
        angle = math.radians(candidate.bearing_deg)
        measured = CandidateScore(
            candidate_id=candidate.candidate_id,
            subject_share=subject,
            ground_share=sum(
                shares.get(k, 0) for k in ("site_road", "service_yard", "site_ground")
            ),
            legible_roles=sum(v > 0.005 for v in shares.values()),
            corner_balance=abs(math.sin(2 * angle)),
            occlusion=0,
            role_targets_visible=shares.get(target_role, 0),
            feasible=not collision and subject > 0.01,
            notes="Corner score is an axis prior; office purpose may target source entrance only; "
            "hidden programme and occlusion are unknown",
        )
        score = score_candidate(measured, ROLE_OBJECTIVES[camera.role])
        ranked.setdefault(camera.role, []).append((candidate, score))
        rows.append(
            {
                "candidate_id": candidate.candidate_id,
                "camera": camera.model_dump(mode="json"),
                "score": score,
                "measurement": asdict(measured),
                "evidence_ref": str(folder / "base_rgb.png"),
            }
        )
        left, top = (i % 4) * 384, (i // 4) * 240
        with Image.open(folder / "base_rgb.png") as image:
            contact.paste(ImageOps.fit(image.convert("RGB"), (384, 216)), (left, top))
        draw.text(
            (left + 4, top + 219), f"{camera.view_id} {camera.role.value} {score:.2f}", fill="white"
        )
    selected = select_view_set(ranked)
    contact.save(root / "contact_sheet.jpg", quality=90)
    result = {
        "search_version": "source-eye-height-v3",
        "view_set_id": job.view_set_id,
        "scope": "source_geometry_only",
        "output_camera_verified": False,
        "candidates": rows,
        "suggested_ids": [c.candidate_id for c in selected],
    }
    write_json(root / "ranking.json", result)
    return result
