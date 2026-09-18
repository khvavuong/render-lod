"""Opt-in pilot: user-selected design -> source camera search -> six review-only images."""

import argparse
import json
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from v365_archviz import api
from v365_archviz.application.run_generation_job import RunGenerationJob
from v365_archviz.artifacts import atomic_write


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--view-set", required=True)
    parser.add_argument("--anchor", choices=("site", "facade"), required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--generate", action="store_true", help="At most six paid image calls")
    args = parser.parse_args()
    if not args.execute:
        print("Dry-run. --execute registers the chosen design and renders source camera previews.")
        print("Add --generate for at most six image calls. No automatic delivery approval.")
        return 0
    api._generation_dispatcher = SimpleNamespace(submit=lambda _: None)
    prefix = f"/v1/view-sets/{args.view_set}"
    with TestClient(api.app) as client:
        progress = client.get(prefix + "/reference-progress")
        progress.raise_for_status()
        if not progress.json()["design"]:
            response = client.post(
                prefix + "/design-registration",
                json={
                    "anchor": args.anchor,
                    "reviewer": "user-selected-proposal",
                    "design_notes": "Continue the selected proposal, not a global template. "
                    "Vietnam context; unapproved programme and unseen surfaces remain unknown.",
                },
            )
            response.raise_for_status()
        if not progress.json()["selection"] and (
            not progress.json()["ranking"]
            or progress.json()["ranking"].get("search_version") != "source-eye-height-v3"
        ):
            print("Rendering source-only camera candidates", flush=True)
            response = client.post(prefix + "/shots/search")
            response.raise_for_status()
        progress = client.get(prefix + "/reference-progress").json()
        if not progress["selection"]:
            ids = progress["ranking"]["suggested_ids"]
            if len(ids) != 6:
                raise RuntimeError(
                    "Not all purposes have feasible candidates; inspect contact sheet"
                )
            response = client.post(prefix + "/shots/select", json={"candidate_ids": ids})
            response.raise_for_status()
        if args.generate:
            job = client.get(prefix).json()
            if job["state"] == "design_master_review":
                response = client.post(prefix + "/registered-generation")
                response.raise_for_status()
            print("Running main worker, six-call cap; output remains review-only", flush=True)
            result = RunGenerationJob().execute(job["job_id"])
            print(result.state.value, result.error_message, flush=True)
        progress = client.get(prefix + "/reference-progress").json()
        outputs = client.get(prefix + "/outputs").json()
        target = Path(".artifacts/reference_led_registered_pilot") / args.view_set / "result.json"
        atomic_write(
            target,
            json.dumps(
                {"progress": progress, "outputs": outputs}, ensure_ascii=False, indent=2
            ).encode(),
        )
        print(target, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
