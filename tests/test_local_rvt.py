from pathlib import Path

from v365_archviz.providers.local_rvt import LocalRvtInspector

SAMPLE = Path("resource/model_lod100_sample.rvt")


def test_inspects_sample_rvt() -> None:
    result = LocalRvtInspector().inspect(SAMPLE)

    assert result.format_version == "2026"
    assert result.build == "20251103_1515(x64)"
    assert result.project_name == "NHÀ XƯỞNG"
    assert result.total_area == "66080.00 m²"
    assert result.external_reference_count == 2
    assert result.preview_png is not None
    assert len(result.sha256) == 64


def test_manifest_excludes_original_machine_path() -> None:
    result = LocalRvtInspector().inspect(SAMPLE)
    manifest = result.to_manifest()

    assert "last_save_path" not in str(manifest)
    assert manifest["source"]["file_name"] == SAMPLE.name  # type: ignore[index]
