from v365_archviz.domain.references import ReferenceRole, evaluate_reference_compatibility


def test_accepts_presentation_grade_landscape_reference() -> None:
    result = evaluate_reference_compatibility(1920, 1080, ReferenceRole.FACTORY_DESIGN)

    assert result.compatible
    assert result.findings == ()


def test_rejects_small_or_portrait_reference() -> None:
    result = evaluate_reference_compatibility(360, 640, ReferenceRole.CONTEXT_REALISM)

    assert not result.compatible
    assert set(result.findings) == {
        "reference_resolution_too_low",
        "reference_aspect_ratio_not_architectural_landscape",
    }
