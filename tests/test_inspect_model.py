import json
from pathlib import Path

from v365_archviz.application.inspect_model import InspectModel


def test_writes_content_addressed_artifacts(tmp_path: Path) -> None:
    first = InspectModel().execute(Path("resource/model_lod100_sample.rvt"), tmp_path)
    second = InspectModel().execute(Path("resource/model_lod100_sample.rvt"), tmp_path)

    assert first.manifest_path == second.manifest_path
    assert first.preview_path == second.preview_path
    assert first.preview_path is not None and first.preview_path.is_file()
    manifest = json.loads(first.manifest_path.read_text(encoding="utf-8"))
    assert manifest["source"]["sha256"] == first.inspection.sha256
