"""Export checked-in JSON schemas from their authoritative Pydantic contracts."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from v365_archviz.artifacts import atomic_write
from v365_archviz.domain.controlled_realism import (
    AssetLibraryManifest,
    CertificationReport,
    ControlPackManifest,
    ControlPolicy,
)
from v365_archviz.domain.design import DesignBrief, DesignDNA
from v365_archviz.domain.qa import ConsistencyReport, RepairRequest
from v365_archviz.domain.scene import CanonicalScene
from v365_archviz.domain.video import VideoPlan
from v365_archviz.domain.workflow import ViewSet, ViewSetGenerationRequest


def main() -> None:
    check_only = "--check" in sys.argv[1:]
    unknown = set(sys.argv[1:]) - {"--check"}
    if unknown:
        raise SystemExit(f"unknown arguments: {', '.join(sorted(unknown))}")
    target = Path("schemas")
    if not check_only:
        target.mkdir(exist_ok=True)
    models = {
        "canonical_scene.schema.json": CanonicalScene,
        "design_dna.schema.json": DesignDNA,
        "design_brief.schema.json": DesignBrief,
        "view_set.schema.json": ViewSet,
        "view_set_generation_request.schema.json": ViewSetGenerationRequest,
        "consistency_report.schema.json": ConsistencyReport,
        "repair_request.schema.json": RepairRequest,
        "video_plan.schema.json": VideoPlan,
        "asset_library_manifest.schema.json": AssetLibraryManifest,
        "control_policy.schema.json": ControlPolicy,
        "control_pack_manifest.schema.json": ControlPackManifest,
        "certification_report.schema.json": CertificationReport,
    }
    drifted: list[str] = []
    for file_name, model in models.items():
        path = target / file_name
        encoded = (json.dumps(model.model_json_schema(), indent=2, sort_keys=True) + "\n").encode(
            "utf-8"
        )
        if check_only:
            if not path.is_file() or path.read_bytes() != encoded:
                drifted.append(file_name)
        else:
            atomic_write(path, encoded)
    if drifted:
        raise SystemExit(f"schema drift detected: {', '.join(drifted)}")


if __name__ == "__main__":
    main()
