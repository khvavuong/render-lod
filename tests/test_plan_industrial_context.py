from v365_archviz.application.plan_industrial_context import PlanIndustrialContext
from v365_archviz.domain.design import SiteDesign


def test_context_plan_is_stable_and_outside_project(valid_scene) -> None:  # type: ignore[no-untyped-def]
    site = SiteDesign(
        surrounding_context_mode="conceptual_industrial_park",
        surrounding_context_count=6,
        context_opacity=0.24,
    )

    first = PlanIndustrialContext().execute(valid_scene, "R01", site)
    second = PlanIndustrialContext().execute(valid_scene, "R01", site)

    assert first.model_dump_json() == second.model_dump_json()
    assert first.mode == "conceptual_industrial_park"
    assert len(first.roads) == 4
    assert len(first.proxy_buildings) == 6
    for proxy in first.proxy_buildings:
        box = proxy.bounding_box
        assert (
            box.maximum[0] <= 0
            or box.minimum[0] >= 60
            or box.maximum[1] <= -10
            or box.minimum[1] >= 40
        )
        assert proxy.opacity == 0.24


def test_authored_only_never_creates_context(valid_scene) -> None:  # type: ignore[no-untyped-def]
    result = PlanIndustrialContext().execute(
        valid_scene,
        "R01",
        SiteDesign(surrounding_context_mode="authored_only"),
    )

    assert result.mode == "authored_only"
    assert not result.roads
    assert not result.proxy_buildings
