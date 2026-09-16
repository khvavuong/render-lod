import json
from pathlib import Path

import pytest
from PIL import Image

from v365_archviz.application.verify_massing import VerifyMassing
from v365_archviz.errors import InvalidModelError
from v365_archviz.providers.gemini_massing_judge import (
    MassingVerdict,
    _collect_text,
    _extract_json,
)


class _StubJudge:
    """Return a scripted count per view so the service logic can be tested offline."""

    def __init__(self, counts: dict[str, int | None]) -> None:
        self.counts = counts
        self.calls: list[tuple[str, int]] = []

    def verify(
        self, view_id: str, base: Path, generated: Path, expected: int
    ) -> MassingVerdict:
        self.calls.append((view_id, expected))
        count = self.counts[view_id]
        return MassingVerdict(
            view_id=view_id,
            expected_volume_count=expected,
            base_volume_count=None if count is None else expected,
            generated_volume_count=count,
            matches=None if count is None else count == expected,
            notes="",
            raw_response="",
        )


def _scene(tmp_path: Path, view_ids: tuple[str, ...]) -> tuple[Path, Path, Path, Path]:
    render = tmp_path / "renders"
    generated = tmp_path / "generated"
    for view_id in view_ids:
        (render / view_id).mkdir(parents=True)
        (generated / view_id).mkdir(parents=True)
        Image.new("RGB", (8, 8), (200, 200, 200)).save(render / view_id / "base_rgb.png")
        Image.new("RGB", (8, 8), (180, 180, 180)).save(
            generated / view_id / "unbranded_refined.jpg"
        )
    view_set = tmp_path / "view_set.json"
    view_set.write_text(
        json.dumps(
            {
                "view_set_id": "rev-design-standard-v32",
                "design_revision": "R01-abcdef123456",
                "cameras": [
                    {
                        "view_id": view_id,
                        "role": role,
                        "position": [10.0, 10.0, 10.0],
                        "target": [0.0, 0.0, 0.0],
                        "focal_length_mm": 32.0,
                        "sensor_width_mm": 36.0,
                        "aspect_ratio": "16:9",
                    }
                    for view_id, role in zip(view_ids, ("overall", "context"), strict=False)
                ],
            }
        ),
        encoding="utf-8",
    )
    design = tmp_path / "design_dna.json"
    return render, generated, view_set, design


def _write_design(path: Path, assemblies: int) -> None:
    from v365_archviz.domain.design import (
        BuildingDesign,
        DesignDNA,
        DesignLanguage,
        EnvironmentDesign,
        RoofAssembly,
        RoofDesign,
    )
    from v365_archviz.domain.scene import BoundingBox

    design = DesignDNA(
        project_id="project",
        design_revision="R01-abcdef123456",
        design_language=DesignLanguage(
            style="style",
            primary_material="primary",
            secondary_material="secondary",
            office_material="office",
        ),
        environment=EnvironmentDesign(
            time="09:00",
            weather="clear",
            sun_azimuth_deg=120,
            sun_elevation_deg=45,
            white_balance_k=5600,
        ),
        buildings=tuple(
            BuildingDesign(building_id=f"b-{index}", roof=RoofDesign(roof_type="gable"))
            for index in range(assemblies)
        ),
        roof_assemblies=tuple(
            RoofAssembly(
                assembly_id=f"roof-{index}",
                building_ids=(f"b-{index}",),
                bounding_box=BoundingBox(
                    minimum=(0.0, float(index) * 20, 0.0),
                    maximum=(50.0, float(index) * 20 + 10, 9.0),
                ),
                roof=RoofDesign(roof_type="gable"),
            )
            for index in range(assemblies)
        ),
        grammar_version="grammar-v1",
        asset_library_version="assets-v1",
    )
    path.write_text(design.model_dump_json(), encoding="utf-8")


def test_extract_json_reads_a_verdict_wrapped_in_prose() -> None:
    value = _extract_json('Sure! {"generated_volume_count": 4, "matches": false} done')

    assert value == {"generated_volume_count": 4, "matches": False}


def test_extract_json_returns_none_without_a_verdict() -> None:
    assert _extract_json("no json here") is None


def test_collect_text_walks_an_unknown_response_shape() -> None:
    body = {"output": [{"content": [{"type": "text", "text": "count is 2"}]}]}

    assert "count is 2" in _collect_text(body)


def test_report_fails_when_a_view_shows_more_volumes_than_authored(tmp_path: Path) -> None:
    render, generated, view_set, design = _scene(tmp_path, ("view-01", "view-02"))
    _write_design(design, 2)
    judge = _StubJudge({"view-01": 4, "view-02": 2})

    report = VerifyMassing().execute(judge, render, generated, view_set, design)

    assert report.failed_view_ids == ("view-01",)
    assert not report.passed
    # The authored count must come from the scene, never from the provider's own echo.
    assert {expected for _, expected in judge.calls} == {2}
    document = json.loads(report.report_path.read_text(encoding="utf-8"))
    assert document["expected_volume_count"] == 2
    assert document["status"] == "fail"


def test_report_passes_when_every_view_matches(tmp_path: Path) -> None:
    render, generated, view_set, design = _scene(tmp_path, ("view-01", "view-02"))
    _write_design(design, 2)

    report = VerifyMassing().execute(
        _StubJudge({"view-01": 2, "view-02": 2}), render, generated, view_set, design
    )

    assert report.passed
    assert report.failed_view_ids == ()


def test_unparsable_verdict_is_unverified_rather_than_a_pass(tmp_path: Path) -> None:
    render, generated, view_set, design = _scene(tmp_path, ("view-01",))
    _write_design(design, 2)

    report = VerifyMassing().execute(
        _StubJudge({"view-01": None}), render, generated, view_set, design
    )

    assert report.unverified_view_ids == ("view-01",)
    assert not report.passed


def test_missing_generated_image_is_rejected(tmp_path: Path) -> None:
    render, generated, view_set, design = _scene(tmp_path, ("view-01",))
    _write_design(design, 2)
    (generated / "view-01" / "unbranded_refined.jpg").unlink()

    with pytest.raises(InvalidModelError):
        VerifyMassing().execute(
            _StubJudge({"view-01": 2}), render, generated, view_set, design
        )
