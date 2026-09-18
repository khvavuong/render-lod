"""Attach an explicit advisory review and compose a diagnostic board, never approve delivery."""

import argparse
import json
from pathlib import Path

from v365_archviz.application.compose_viewset_board import ComposeViewSetBoard
from v365_archviz.application.reference_delivery import sha
from v365_archviz.application.run_generation_job import _JobPaths
from v365_archviz.application.run_reference_proposal import write_json
from v365_archviz.config import Settings
from v365_archviz.providers.local_jobs import LocalJobRepository


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("review_json", type=Path)
    args = parser.parse_args()
    review = json.loads(args.review_json.read_text(encoding="utf-8"))
    settings = Settings.from_env()
    job = LocalJobRepository(settings.artifact_dir / "metadata").get_by_view_set(
        review["view_set_id"]
    )
    root = _JobPaths.from_job(settings.artifact_dir, job).generated_root / "registered"
    qa = json.loads((root / "stage_qa.json").read_text())
    review["output_hashes"] = qa["output_hashes"]
    review["qa_sha256"] = sha(root / "stage_qa.json")
    review["human_approved"] = False
    review["geometry_certified"] = False
    for view_id, expected in qa["output_hashes"].items():
        files = list((root / view_id).glob("refined.*"))
        if len(files) != 1 or sha(files[0]) != expected:
            raise RuntimeError("Advisory review output hash changed")
    write_json(root / "agent_visual_review.json", review)
    target = (
        settings.artifact_dir
        / "reference_led_registered_pilot"
        / job.view_set_id
        / "review_board.jpg"
    )
    ComposeViewSetBoard().execute(root, target)
    print(target)
    print("Diagnostic board only; no delivery approval or job state change.")


if __name__ == "__main__":
    main()
