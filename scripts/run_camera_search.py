"""E1 — search for a view set instead of deriving one from tuned rules.

Renders a candidate pool through the cheap `camera_scoring` profile, measures what each candidate
actually shows from its semantic pass, and selects a diverse set. Writes a ranking table and a
contact sheet so the result can be reviewed against the current planner rather than trusted.
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from v365_archviz.application.camera_candidates import (
    ROLE_OBJECTIVES,
    CameraCandidate,
    CandidateScore,
    propose_candidates,
    score_candidate,
    select_view_set,
)
from v365_archviz.application.plan_cameras import PlanStandardCameras
from v365_archviz.domain.photography_pack import PhotographyPack
from v365_archviz.domain.scene import CanonicalScene
from v365_archviz.domain.workflow import Camera, ViewRole, ViewSet

#: Semantic roles that belong to the project itself rather than its surroundings.
SUBJECT_ROLES = frozenset(
    {
        "main_shed",
        "office_block",
        "roof",
        "primary_facade",
        "facade_secondary",
        "glazing",
        "brand_accent",
        "design_detail",
        "utility_block",
        "main_entrance",
        "secondary_entrance",
    }
)
GROUND_ROLES = frozenset({"site_road", "service_yard", "parking", "sidewalk", "site_ground"})
OCCLUDER_ROLES = frozenset({"tree", "vehicle", "person", "context_building"})
#: What each role's slot exists to show. A candidate that cannot see it is the wrong photograph.
ROLE_TARGETS = {
    ViewRole.OFFICE_HERO: frozenset({"main_entrance", "office_block", "glazing"}),
    ViewRole.LOADING_DETAIL: frozenset({"loading_zone", "main_entrance"}),
    ViewRole.HERO: frozenset({"loading_zone", "main_shed"}),
}
#: Below this share of frame a role is present but not legible, so it should not earn credit.
LEGIBLE_SHARE = 0.005


def _role_shares(view_dir: Path) -> dict[str, float]:
    manifest = json.loads((view_dir / "semantic_id_manifest.json").read_text(encoding="utf-8"))
    palette = np.array([entry["srgb8"] for entry in manifest["roles"]], dtype=np.int16)
    names = [entry["semantic_role"] for entry in manifest["roles"]]
    with Image.open(view_dir / "semantic.png") as handle:
        pixels = np.asarray(handle.convert("RGB"), dtype=np.int16)
    flat = pixels.reshape(-1, 3)
    distance = np.abs(flat[:, None, :] - palette[None, :, :]).max(axis=2)
    nearest = distance.argmin(axis=1)
    matched = distance.min(axis=1) < 20
    shares: dict[str, float] = {}
    total = flat.shape[0]
    for index, name in enumerate(names):
        count = int(np.count_nonzero((nearest == index) & matched))
        if count:
            shares[name] = count / total
    return shares


def _corner_balance(view_dir: Path, shares: dict[str, float]) -> float:
    """How evenly the subject splits across the frame's two halves.

    This is centring only, not evidence of two visible facades. Kept for diagnostics;
    ranking uses the surface-normal prior below instead.
    """

    manifest = json.loads((view_dir / "semantic_id_manifest.json").read_text(encoding="utf-8"))
    subject_colours = [
        entry["srgb8"] for entry in manifest["roles"] if entry["semantic_role"] in SUBJECT_ROLES
    ]
    if not subject_colours:
        return 0.0
    with Image.open(view_dir / "semantic.png") as handle:
        pixels = np.asarray(handle.convert("RGB"), dtype=np.int16)
    mask = np.zeros(pixels.shape[:2], dtype=bool)
    for colour in subject_colours:
        mask |= np.abs(pixels - np.array(colour, dtype=np.int16)).max(axis=2) < 20
    if not mask.any():
        return 0.0
    midpoint = mask.shape[1] // 2
    left = int(mask[:, :midpoint].sum())
    right = int(mask[:, midpoint:].sum())
    if left + right == 0:
        return 0.0
    return 1.0 - abs(left - right) / (left + right)


def _normal_corner_prior(scene: CanonicalScene, candidate: CameraCandidate) -> float:
    groups: dict[tuple[float, float], float] = {}
    focus_ids = {
        element.scene_element_id
        for element in scene.elements
        if element.semantic_role.value in {"main_shed", "office_block"}
    }
    for surface in scene.surfaces:
        if surface.element_id not in focus_ids:
            continue
        normal = surface.frame.normal
        if abs(normal[2]) > 0.5:
            continue
        delta = tuple(candidate.position[axis] - surface.frame.origin[axis] for axis in range(3))
        length = math.sqrt(sum(value * value for value in delta))
        facing = sum(normal[axis] * delta[axis] for axis in range(3)) / max(length, 1e-6)
        if facing <= 0:
            continue
        key = (round(normal[0], 2), round(normal[1], 2))
        groups[key] = groups.get(key, 0.0) + facing * surface.width_m * surface.height_m
    ordered = sorted(groups.values(), reverse=True)
    return 2 * ordered[1] / sum(ordered[:2]) if len(ordered) >= 2 else 0.0


def measure(view_dir: Path, candidate: CameraCandidate, scene: CanonicalScene) -> CandidateScore:
    shares = _role_shares(view_dir)
    subject = sum(share for role, share in shares.items() if role in SUBJECT_ROLES)
    ground = sum(share for role, share in shares.items() if role in GROUND_ROLES)
    occluders = sum(share for role, share in shares.items() if role in OCCLUDER_ROLES)
    targets = ROLE_TARGETS.get(candidate.role, frozenset())
    target_share = sum(share for role, share in shares.items() if role in targets)
    legible = sum(1 for share in shares.values() if share >= LEGIBLE_SHARE)
    collision = any(
        element.semantic_role.value in {"main_shed", "office_block", "context_building"}
        and all(
            element.bounding_box.minimum[axis]
            <= candidate.position[axis]
            <= element.bounding_box.maximum[axis]
            for axis in range(3)
        )
        for element in scene.elements
    )
    return CandidateScore(
        candidate_id=candidate.candidate_id,
        subject_share=subject,
        ground_share=ground,
        legible_roles=legible,
        corner_balance=_normal_corner_prior(scene, candidate),
        occlusion=occluders / max(subject + occluders, 1e-6),
        role_targets_visible=target_share,
        feasible=subject > 0.01 and not collision,
        notes="camera inside a building"
        if collision
        else ""
        if subject > 0.01
        else "subject not visible from this camera",
    )


def _write_view_set(path: Path, candidates: tuple[CameraCandidate, ...], revision: str) -> None:
    cameras = tuple(
        Camera(
            view_id=f"view-{index:02d}",
            role=candidate.role,
            position=candidate.position,
            target=candidate.target,
            focal_length_mm=candidate.focal_length_mm,
            sensor_width_mm=36,
            aspect_ratio="16:9",
        )
        for index, candidate in enumerate(candidates, start=1)
    )
    view_set = ViewSet(view_set_id=f"{revision}-search", design_revision=revision, cameras=cameras)
    path.write_text(view_set.model_dump_json(indent=2), encoding="utf-8")


def _render(scene: Path, dna: Path, view_set: Path, output: Path, workspace: str) -> None:
    workspace_path = Path(workspace).resolve()

    def container_path(path: Path) -> str:
        return "/workspace/" + path.resolve().relative_to(workspace_path).as_posix()

    subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "-e",
            "HOME=/tmp",
            "-v",
            f"{workspace}:/workspace",
            "--entrypoint",
            "blender",
            "v365-archviz-renderer:layered-v1",
            "--background",
            "--python",
            "/workspace/scripts/blender/render_conditioning.py",
            "--",
            "--scene",
            container_path(scene),
            "--design-dna",
            container_path(dna),
            "--asset-library",
            "/workspace/assets/pbr-v1/asset_library_manifest.json",
            "--view-set",
            container_path(view_set),
            "--output",
            container_path(output),
            "--profile",
            "camera_scoring",
        ],
        check=True,
        capture_output=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scene", type=Path)
    parser.add_argument("--design-dna", type=Path, required=True)
    parser.add_argument("--photography-pack", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workspace", default=str(Path.cwd()).replace("\\", "/"))
    arguments = parser.parse_args()

    scene = CanonicalScene.model_validate_json(arguments.scene.read_text(encoding="utf-8"))
    pack = PhotographyPack.load(arguments.photography_pack)
    focus = [
        element
        for element in scene.elements
        if element.semantic_role.value in {"main_shed", "office_block"}
    ]
    if not focus:
        raise SystemExit(
            "no identified focus buildings; review source classification before search"
        )
    boxes = [element.bounding_box for element in focus]
    minimum = tuple(min(box.minimum[axis] for box in boxes) for axis in range(3))
    maximum = tuple(max(box.maximum[axis] for box in boxes) for axis in range(3))
    centre = tuple((minimum[axis] + maximum[axis]) / 2 for axis in range(3))
    bounds = (minimum, maximum)  # type: ignore[arg-type]
    target = (centre[0], centre[1], minimum[2] + (maximum[2] - minimum[2]) * 0.35)

    arguments.output.mkdir(parents=True, exist_ok=True)
    anchor_set = PlanStandardCameras().execute(
        arguments.scene,
        arguments.design_dna,
        arguments.photography_pack,
        output_path=arguments.output / "analytic_anchor_view_set.json",
    )
    anchors = {camera.role: camera for camera in anchor_set.cameras}
    pool: list[CameraCandidate] = []
    for role in pack.roles:
        role_target = anchors[role].target if role in anchors else target
        role_bounds = bounds
        if role in {ViewRole.OFFICE_HERO, ViewRole.LOADING_DETAIL, ViewRole.HERO}:
            nearest = min(
                focus,
                key=lambda element: math.dist(
                    tuple(
                        (element.bounding_box.minimum[axis] + element.bounding_box.maximum[axis])
                        / 2
                        for axis in range(3)
                    ),
                    role_target,
                ),
            )
            role_bounds = (nearest.bounding_box.minimum, nearest.bounding_box.maximum)
        pool.extend(
            propose_candidates(
                role,
                pack.framing_for(role),
                role_bounds,
                role_target,
                distance_factors=(1.0,),
                elevation_offsets=(0.0,),
            )
        )
    print(f"candidate pool: {len(pool)} across {len(pack.roles)} roles")

    view_set_path = arguments.output / "candidate_view_set.json"
    design_revision = json.loads(arguments.design_dna.read_text(encoding="utf-8"))[
        "design_revision"
    ]
    _write_view_set(view_set_path, tuple(pool), design_revision)
    renders = arguments.output / "renders"
    _render(arguments.scene, arguments.design_dna, view_set_path, renders, arguments.workspace)

    ranked: dict[ViewRole, list[tuple[CameraCandidate, float]]] = {}
    rows: list[dict[str, object]] = []
    for index, candidate in enumerate(pool, start=1):
        view_dir = renders / f"view-{index:02d}"
        if not (view_dir / "semantic.png").is_file():
            continue
        measured = measure(view_dir, candidate, scene)
        value = score_candidate(measured, ROLE_OBJECTIVES[candidate.role])
        ranked.setdefault(candidate.role, []).append((candidate, value))
        rows.append(
            {
                "candidate_id": candidate.candidate_id,
                "render_view_id": f"view-{index:02d}",
                "role": candidate.role.value,
                "bearing_deg": candidate.bearing_deg,
                "elevation_deg": candidate.elevation_deg,
                "distance_m": round(candidate.distance_m, 1),
                "score": round(value, 4),
                "subject_share": round(measured.subject_share, 4),
                "ground_share": round(measured.ground_share, 4),
                "legible_roles": measured.legible_roles,
                "corner_balance": round(measured.corner_balance, 4),
                "occlusion": round(measured.occlusion, 4),
                "role_targets_visible": round(measured.role_targets_visible, 4),
            }
        )

    selected = select_view_set(ranked)
    if len(selected) != len(pack.roles):
        print("Incomplete search: missing feasible roles; this is not an approved camera set")
    (arguments.output / "candidate_ranking.json").write_text(
        json.dumps(sorted(rows, key=lambda row: -float(row["score"])), indent=2) + "\n",
        encoding="utf-8",
    )
    _write_view_set(arguments.output / "selected_view_set.json", selected, design_revision)
    # Diagnostic board only: selection remains unapproved until conditioning and visual review.
    sheet = Image.new("RGB", (256 * 8, 176 * math.ceil(len(rows) / 8)), "white")
    draw = ImageDraw.Draw(sheet)
    for index, row in enumerate(rows):
        x, y = (index % 8) * 256, (index // 8) * 176
        with Image.open(renders / str(row["render_view_id"]) / "semantic.png") as source:
            sheet.paste(source.convert("RGB").resize((256, 144)), (x, y))
        draw.text(
            (x + 4, y + 146),
            f"{row['role']} b={row['bearing_deg']:.0f} score={row['score']:.3f}",
            fill="black",
        )
    if rows:
        sheet.save(arguments.output / "candidate_contact_sheet.jpg", quality=90)
    print(f"\n{'role':16s} {'bearing':>8s} {'elev':>6s} {'dist':>7s} {'score':>7s}")
    by_id = {row["candidate_id"]: row for row in rows}
    for candidate in selected:
        row = by_id[candidate.candidate_id]
        print(
            f"{candidate.role.value:16s} {candidate.bearing_deg:8.0f} "
            f"{candidate.elevation_deg:6.0f} {candidate.distance_m:7.0f} "
            f"{float(row['score']):7.3f}"
        )
    return 0 if len(selected) == len(pack.roles) else 2


if __name__ == "__main__":
    raise SystemExit(main())
