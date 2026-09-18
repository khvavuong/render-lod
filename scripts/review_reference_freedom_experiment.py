"""Opaque-ID aesthetic review and separate constraint audit, with advisory-only verdicts.

Never modifies generated images. Boards/CSV are diagnostic review aids, not deliverables.
One VLM reviewer is not two human reviewers; a pass is not geometry certification.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from pathlib import Path

import httpx
from PIL import Image, ImageDraw

from v365_archviz.artifacts import atomic_write
from v365_archviz.config import Settings
from v365_archviz.providers.gemini import DEFAULT_ENDPOINT, _image_block
from v365_archviz.providers.gemini_view_judge import _collect_text, _extract_json

QUALITY_PROMPT = """You are an architectural marketing art director auditing an experiment.
IMAGE 1 is the user's target-quality reference board, NOT source geometry. Ignore its captions.
IMAGE 2 is one full-frame candidate. You do not know which treatment made it.
Score each 1-5: 1 unacceptable, 2 weak, 3 usable concept, 4 strong shortlist, 5 publication-quality.
Do not reward any particular facade kit: judge architectural hierarchy, proportions, buildability,
credible industrial operation and appropriateness to this image's apparent purpose.
Evaluate the ORIGINAL single frame, not brochure layout. Merely high resolution is not realism.
Inspect material transitions, glass reflections, roof/facade construction, vehicle scale,
foreground use, subject framing, vegetation, placeholder masses and invented text/branding.
Compare ambition and quality to the reference, not exact footprint, camera or copied design.
Return JSON only:
{"composition": 1, "design": 1, "realism": 1, "material_lighting": 1,
 "reference_alignment": 1, "operational_plausibility": 1,
 "critical_defects": ["specific visible defect, or empty list if none"],
 "strongest": "short evidence", "weakest": "short evidence"}.
No score is a geometry certification or approval of a coherent six-view project."""

FACT_PROMPT = """You are a conservative source-constraint reviewer, NOT an aesthetic judge.
Compare the candidate photograph to the source-envelope summary and, when supplied, a registered
render. The render's low-poly planting, colour, glazing style and procedural facade are proposals,
not source requirements. New facade articulation may be permissible.
If a programme lock is supplied,
the functional openings visible in the registered render are binding, not invisible/rear doors.
Do not infer exact dimensions or certify 3D consistency from one 2D image. A partial office view
cannot establish the total campus building count. Use null whenever the evidence is insufficient.
Camera checks apply ONLY if a registered render is supplied. Otherwise camera choice is free.
Return JSON only:
{"apparent_focus_building_count": null, "source_layout_plausible": null,
 "camera_matches": null, "visible_programme_retained": null,
 "notes": "specific observable evidence / unknowns"}.
camera_matches may be same, shifted, different, or null. Boolean fields must be true/false/null.
Do not approve an image because it is attractive.
These are review findings, not measured geometry."""

SCORES = (
    "composition",
    "design",
    "realism",
    "material_lighting",
    "reference_alignment",
    "operational_plausibility",
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: object) -> None:
    atomic_write(path, json.dumps(value, ensure_ascii=False, indent=2).encode() + b"\n")


class ReviewUnavailable(RuntimeError):
    """A failed/uncertain paid review is unknown, never permission to retry."""


def judge(client: httpx.Client, model: str, api_key: str, blocks: list[dict], output: Path) -> dict:
    fingerprint = hashlib.sha256(
        json.dumps({"model": model, "blocks": blocks}, sort_keys=True).encode()
    ).hexdigest()
    if output.is_file():
        existing = json.loads(output.read_text(encoding="utf-8"))
        if existing.get("request_signature") != fingerprint:
            raise ValueError(f"stale review: {output}; choose a new review directory")
        if existing.get("status") != "complete":
            raise ReviewUnavailable(f"uncertain prior judge call: {output}; no automatic retry")
        return existing["verdict"]
    write_json(output, {"status": "in_flight", "request_signature": fingerprint, "model": model})
    try:
        response = client.post(
            DEFAULT_ENDPOINT,
            json={"model": model, "input": blocks, "store": False},
            headers={"x-goog-api-key": api_key},
        )
        response.raise_for_status()
        text = _collect_text(response.json())
        verdict = _extract_json(text)
        if verdict is None:
            raise ValueError("judge did not return JSON")
        write_json(
            output,
            {
                "status": "complete",
                "request_signature": fingerprint,
                "model": model,
                "verdict": verdict,
                "raw_text": text,
            },
        )
        return verdict
    except (httpx.HTTPError, ValueError) as exc:
        write_json(
            output,
            {
                "status": "failed",
                "request_signature": fingerprint,
                "error_type": type(exc).__name__,
            },
        )
        raise ReviewUnavailable(f"review unavailable: {type(exc).__name__}") from exc


def advisory_judge(*args) -> dict:
    try:
        return judge(*args)
    except ReviewUnavailable as exc:
        print(str(exc), flush=True)
        return {"review_status": "unavailable", "reason": str(exc)}


def quality_shortlist(verdict: dict) -> bool:
    return (
        all(
            isinstance(verdict.get(name), int)
            and not isinstance(verdict[name], bool)
            and 4 <= verdict[name] <= 5
            for name in SCORES[:4]
        )
        and verdict.get("critical_defects") == []
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    parser.add_argument("--execute", action="store_true", help="enable at most 42 judge calls")
    arguments = parser.parse_args()
    config = json.loads(arguments.config.read_text(encoding="utf-8"))
    root = Path(config["output_root"])
    plan = json.loads((root / "experiment_plan.json").read_text(encoding="utf-8"))
    records = []
    for sample in plan["samples"]:
        manifest = Path(sample["directory"]) / "manifest.json"
        if not manifest.is_file():
            raise ValueError("generation incomplete; do not review a biased partial set")
        record = json.loads(manifest.read_text(encoding="utf-8"))
        if record["status"] != "complete" or record["output_sha256"] != digest(
            Path(record["output"])
        ):
            raise ValueError("generation failed or image changed")
        record["opaque_id"] = hashlib.sha256(record["request_signature"].encode()).hexdigest()[:10]
        records.append(record)
    records.sort(key=lambda row: row["opaque_id"])
    review = root / "review"
    review.mkdir(parents=True, exist_ok=True)
    # Stable IDs conceal configuration labels from the VLM, not from the coordinating researcher.
    write_json(
        review / "unblinding_key.json",
        {
            row["opaque_id"]: {
                "arm": row["sample"]["arm"],
                "view": row["sample"]["view"],
                "repetition": row["sample"]["repetition"],
                "output": row["output"],
            }
            for row in records
        },
    )
    for arm in sorted({row["sample"]["arm"] for row in records}):
        selected = sorted(
            [row for row in records if row["sample"]["arm"] == arm],
            key=lambda row: (row["sample"]["view"], row["sample"]["repetition"]),
        )
        sheet = Image.new("RGB", (768 * 3, 464 * 2), "white")
        draw = ImageDraw.Draw(sheet)
        for index, row in enumerate(selected):
            x, y = index % 3 * 768, index // 3 * 464
            with Image.open(row["output"]) as source:
                sheet.paste(source.convert("RGB").resize((768, 432)), (x, y))
            draw.text(
                (x + 8, y + 436),
                f"{row['sample']['view']} rep-{row['sample']['repetition']} | {row['opaque_id']}",
                fill="black",
            )
        buffer = io.BytesIO()
        sheet.save(buffer, format="JPEG", quality=94)
        atomic_write(review / f"{arm}_board.jpg", buffer.getvalue())
    sheet_path = review / "human_score_sheet.csv"
    if not sheet_path.is_file():
        buffer = io.StringIO(newline="")
        writer = csv.writer(buffer)
        writer.writerow(["opaque_id", *SCORES, "critical_defects", "notes"])
        for row in records:
            writer.writerow([row["opaque_id"], *["" for _ in SCORES], "", ""])
        atomic_write(sheet_path, buffer.getvalue().encode())
    print(f"{len(records)} images ready for review; no human scores have been invented", flush=True)
    if not arguments.execute:
        return 0
    if len(records) > 24:
        raise ValueError("review cap exceeded")
    settings = Settings.from_env()
    if not settings.gemini_api_key:
        raise ValueError("Gemini is not configured")
    rows = []
    with httpx.Client(timeout=httpx.Timeout(180, connect=15)) as client:
        for record in records:
            sample = record["sample"]
            code = record["opaque_id"]
            quality = advisory_judge(
                client,
                settings.gemini_image_model,
                settings.gemini_api_key,
                [
                    {"type": "text", "text": QUALITY_PROMPT},
                    _image_block(Path(config["references"][0]["path"])),
                    _image_block(Path(record["output"])),
                ],
                review / "quality" / f"{code}.json",
            )
            facts = None
            if sample["arm"] != "R0_reference_free":
                fact_blocks = [
                    {
                        "type": "text",
                        "text": FACT_PROMPT
                        + "\nSource envelopes:\n"
                        + json.dumps(plan["contract"]["source_focus_elements"]),
                    }
                ]
                if sample["arm"] in {"R2_registered_camera", "R3_locked_programme"}:
                    fact_blocks.extend(
                        [
                            {"type": "text", "text": "REGISTERED RENDER:"},
                            _image_block(Path(config["views"][sample["view"]]["base"])),
                        ]
                    )
                if sample["arm"] == "R3_locked_programme":
                    fact_blocks.append(
                        {
                            "type": "text",
                            "text": "Programme lock:\n"
                            + json.dumps(plan["contract"]["unapproved_pipeline_programme"]),
                        }
                    )
                fact_blocks.extend(
                    [
                        {"type": "text", "text": "CANDIDATE PHOTOGRAPH:"},
                        _image_block(Path(record["output"])),
                    ]
                )
                facts = advisory_judge(
                    client,
                    settings.gemini_image_model,
                    settings.gemini_api_key,
                    fact_blocks,
                    review / "facts" / f"{code}.json",
                )
            rows.append(
                {
                    "opaque_id": code,
                    "arm": sample["arm"],
                    "view": sample["view"],
                    "repetition": sample["repetition"],
                    "output": record["output"],
                    "quality": quality,
                    "quality_shortlist": quality_shortlist(quality),
                    "facts": facts,
                    "marketing_approved": False,
                }
            )
            write_json(
                review / "results.json",
                {
                    "reviewer": "single_same-provider_VLM",
                    "limitations": "Advisory opaque-ID review, not two human reviewers; "
                    "not geometry certification or multi-view consistency.",
                    "review_model": settings.gemini_image_model,
                    "images": rows,
                },
            )
            print(
                f"reviewed {len(rows)}/{len(records)} ({code}); "
                f"shortlist={quality_shortlist(quality)}",
                flush=True,
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
