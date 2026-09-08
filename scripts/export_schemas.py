"""Export checked-in JSON schemas from their authoritative Pydantic contracts."""

from __future__ import annotations

import json
from pathlib import Path

from v365_archviz.domain.design import DesignBrief, DesignDNA
from v365_archviz.domain.qa import ConsistencyReport, RepairRequest
from v365_archviz.domain.scene import CanonicalScene
from v365_archviz.domain.workflow import ViewSet, ViewSetGenerationRequest


def main() -> None:
    target = Path("schemas")
    target.mkdir(exist_ok=True)
    models = {
        "canonical_scene.schema.json": CanonicalScene,
        "design_dna.schema.json": DesignDNA,
        "design_brief.schema.json": DesignBrief,
        "view_set.schema.json": ViewSet,
        "view_set_generation_request.schema.json": ViewSetGenerationRequest,
        "consistency_report.schema.json": ConsistencyReport,
        "repair_request.schema.json": RepairRequest,
    }
    for file_name, model in models.items():
        path = target / file_name
        path.write_text(
            json.dumps(model.model_json_schema(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
