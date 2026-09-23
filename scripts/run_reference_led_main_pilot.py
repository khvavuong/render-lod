"""Exercise real reference upload, job API and production worker; cap two images/job."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from v365_archviz import api
from v365_archviz.application.reference_led_input import VERSION
from v365_archviz.application.run_generation_job import RunGenerationJob
from v365_archviz.artifacts import atomic_write


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--model", default="a7d22ba36b4fa342")
    parser.add_argument("--design", default="R01-30c3e1709447")
    parser.add_argument("--architecture", type=Path, default=Path("resource/sample_image_4.png"))
    parser.add_argument("--materials", type=Path, default=Path("resource/sample_image_3.png"))
    args = parser.parse_args()
    if not args.execute:
        print("No API writes/calls. --execute runs upload/job API then worker, at most 2 images.")
        return 0
    # Dispatcher is suppressed only in this diagnostic process: run the actual worker once.
    api._generation_dispatcher = SimpleNamespace(submit=lambda _: None)
    with TestClient(api.app) as client:
        ids = []
        for path, role in (
            (args.architecture, "factory_design_reference"),
            (args.materials, "construction_material_reference"),
        ):
            uploaded = client.post(
                "/v1/references",
                content=path.read_bytes(),
                headers={
                    "Content-Type": "image/png",
                    "X-Filename": path.name,
                    "X-Reference-Role": role,
                },
            )
            uploaded.raise_for_status()
            ids.append(uploaded.json()["reference_id"])
        created = client.post(
            f"/v1/design-revisions/{args.design}/view-sets",
            json={
                "model_revision": args.model,
                "profile": "marketing_hero",
                "generation_policy": VERSION,
                "reference_ids": ids,
            },
        )
        created.raise_for_status()
        spec = created.json()
        print(f"Main-flow job {spec['job_id']}; fixed budget 2; worker starting", flush=True)
        result = RunGenerationJob().execute(spec["job_id"])
        print(f"Worker stopped at {result.state.value}", flush=True)
        response = client.get(f"/v1/view-sets/{spec['view_set_id']}")
        response.raise_for_status()
        outputs = client.get(f"/v1/view-sets/{spec['view_set_id']}/outputs")
        outputs.raise_for_status()
        summary = {
            "job": response.json(),
            "outputs": outputs.json()["outputs"],
            "human_approved": False,
            "delivery_approved": False,
        }
        destination = api._settings().artifact_dir / "reference_led_main_pilot" / "result.json"
        atomic_write(destination, json.dumps(summary, ensure_ascii=False, indent=2).encode())
        print(f"{len(summary['outputs'])} outputs; summary: {destination}", flush=True)
        return 0 if result.state.value == "design_master_review" else 1


if __name__ == "__main__":
    raise SystemExit(main())
