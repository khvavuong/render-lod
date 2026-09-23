"""Assemble one deliverable view set by choosing between candidate passes.

Every view here was generated more than once. Factual gates run first and remove candidates that
changed the building or the camera; only what survives is offered to the aesthetic judge, so a
handsome image that moved a wall can never win. The set-level diversity check runs last, because
it is a property of the chosen combination rather than of any single frame.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from collections import Counter
from pathlib import Path

from v365_archviz.application.verify_views import VerifyViews
from v365_archviz.config import Settings
from v365_archviz.domain.workflow import ViewSet
from v365_archviz.providers.gemini_artefact_judge import GeminiArtefactJudge
from v365_archviz.providers.gemini_selection_judge import GeminiSelectionJudge
from v365_archviz.providers.gemini_view_judge import GeminiViewJudge


def _image(root: Path, view_id: str) -> Path | None:
    directory = root / view_id
    for pattern in ("unbranded_refined.*", "refined.*"):
        found = sorted(directory.glob(pattern))
        if found:
            return found[0]
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("render_root", type=Path)
    parser.add_argument("--candidate", action="append", required=True, type=Path)
    parser.add_argument("--view-set", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--master-sha256", help="Select one design-master lineage; never mix independent designs"
    )
    parser.add_argument(
        "--proof-tiles",
        type=int,
        default=4,
        help=(
            "tile count for artefact proofing. A whole frame hides small defects: an "
            "orphaned sign fragment was reported clean at 1 tile and caught at 4."
        ),
    )
    arguments = parser.parse_args()

    if arguments.output.exists() and any(arguments.output.iterdir()):
        raise SystemExit(
            "output must be a new or empty directory; existing review artefacts are preserved"
        )
    identities: dict[Path, str] = {}
    for root in arguments.candidate:
        manifest_path = root / "viewset_generation_manifest.json"
        if not manifest_path.is_file():
            raise SystemExit(f"missing design-master provenance: {root}")
        identity = json.loads(manifest_path.read_text(encoding="utf-8")).get("master_sha256")
        if not identity:
            raise SystemExit(f"missing design-master hash: {root}")
        identities[root] = identity
    if arguments.master_sha256:
        arguments.candidate = [
            root for root in arguments.candidate if identities[root] == arguments.master_sha256
        ]
        if not arguments.candidate:
            raise SystemExit("no candidate belongs to the requested design master")
    elif len(set(identities.values())) != 1:
        raise SystemExit(
            "independent Design Masters cannot be mixed; choose a lineage with --master-sha256"
        )

    settings = Settings.from_env()
    view_set = ViewSet.model_validate_json(arguments.view_set.read_text(encoding="utf-8"))
    view_judge = GeminiViewJudge(settings)
    selection_judge = GeminiSelectionJudge(settings)
    artefact_judge = GeminiArtefactJudge(settings)

    # One audit per candidate pass rather than per image, so the report per pass stays reusable.
    # An audit already on disk is reused: these calls cost real money and the images have not
    # changed since they were written.
    audits: list[dict[str, str]] = []
    for root in arguments.candidate:
        existing = root / "view_audit.json"
        document = json.loads(existing.read_text(encoding="utf-8")) if existing.is_file() else {}
        rows = {row["view_id"]: row for row in document.get("views", [])}
        fresh = document.get("view_set_id") == view_set.view_set_id and all(
            (image := _image(root, camera.view_id)) is not None
            and rows.get(camera.view_id, {}).get("image_sha256")
            == hashlib.sha256(image.read_bytes()).hexdigest()
            and rows.get(camera.view_id, {}).get("base_sha256")
            == hashlib.sha256(
                (arguments.render_root / camera.view_id / "base_rgb.png").read_bytes()
            ).hexdigest()
            for camera in view_set.cameras
        )
        if not fresh:
            VerifyViews().execute(
                view_judge, arguments.render_root, root, arguments.view_set, existing
            )
        document = json.loads(existing.read_text(encoding="utf-8"))
        audits.append({row["view_id"]: row["status"] for row in document["views"]})

    arguments.output.mkdir(parents=True, exist_ok=True)
    decisions: list[dict[str, object]] = []
    pending_copies: list[tuple[Path, Path]] = []
    for camera in view_set.cameras:
        eligible: list[tuple[int, Path]] = []
        rejected_for_artefacts: list[dict[str, object]] = []
        for index, root in enumerate(arguments.candidate):
            status = audits[index].get(camera.view_id, "unverified")
            image = _image(root, camera.view_id)
            if image is None or status != "pass":
                continue
            # Proof before ranking. A defect a reader spots first must not be competing with the
            # quality of the light: blind validation showed the aesthetic judge preferring an
            # image whose signage carried an orphaned fragment.
            proof = artefact_judge.proof(camera.view_id, image, tiles=arguments.proof_tiles)
            if proof.status != "pass":
                rejected_for_artefacts.append(
                    {"pass": index + 1, "worst": proof.worst, "notes": proof.notes}
                )
                continue
            eligible.append((index, image))
        fallback = False
        if not eligible:
            decisions.append(
                {"view_id": camera.view_id, "status": "unresolved", "chosen_pass": None}
            )
            continue

        verdict = selection_judge.choose(camera.view_id, tuple(path for _, path in eligible))
        if verdict.best_index is None or not 1 <= verdict.best_index <= len(eligible):
            decisions.append(
                {
                    "view_id": camera.view_id,
                    "status": "unresolved",
                    "chosen_pass": None,
                    "reason": "aesthetic judge did not decide",
                }
            )
            continue
        position = verdict.best_index - 1
        chosen_pass, chosen_path = eligible[position]
        destination = arguments.output / camera.view_id
        destination.mkdir(parents=True, exist_ok=True)
        pending_copies.append((chosen_path, destination / f"unbranded_refined{chosen_path.suffix}"))
        decisions.append(
            {
                "view_id": camera.view_id,
                "role": camera.role.value,
                "eligible_passes": [index + 1 for index, _ in eligible],
                "chosen_pass": chosen_pass + 1,
                "all_candidates_rejected_on_facts": fallback,
                "rejected_for_artefacts": rejected_for_artefacts,
                "reason": verdict.reason,
                "artefacts": verdict.artefacts,
            }
        )
        flag = "  [no candidate passed the factual gates]" if fallback else ""
        print(
            f"{camera.view_id} {camera.role.value:15s} eligible="
            f"{[i + 1 for i, _ in eligible]} chosen=pass {chosen_pass + 1}{flag}"
        )
        if verdict.reason:
            print(f"    {verdict.reason[:100]}")

    # Set-level diversity: a brochure needs different heights and distances, not six drone shots.
    heights = Counter()
    for camera in view_set.cameras:
        eye = camera.position[2]
        heights["aerial" if eye > 40 else "elevated" if eye > 6 else "ground"] += 1
    dominant = heights.most_common(1)[0]
    diverse = dominant[1] <= len(view_set.cameras) * 0.6
    print(f"\nplanned set spread: {dict(heights)}  {'ok' if diverse else 'TOO UNIFORM'}")

    (arguments.output / "selection.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "design_master_sha256": identities[arguments.candidate[0]],
                "status": "blocked"
                if len(pending_copies) != len(view_set.cameras)
                else "requires_set_review",
                "note": (
                    "Factual gates filtered the candidates; the aesthetic judge only ordered "
                    "what survived. Rejected or uncertain views are never exported. "
                    "A complete set still requires human review of design consistency "
                    "and marketing quality."
                ),
                "planned_camera_spread": dict(heights),
                "planned_spread_acceptable": diverse,
                "views": decisions,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    if len(pending_copies) != len(view_set.cameras):
        return 2
    # Different passes can contain different master designs. Keep these as review candidates,
    # never implicitly label them as a marketing-approved deliverable.
    for source, destination in pending_copies:
        shutil.copy2(source, destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
