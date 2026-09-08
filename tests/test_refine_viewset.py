import io
import json
from pathlib import Path

from PIL import Image

from v365_archviz.application.refine_viewset import RefineViewSet
from v365_archviz.domain.design import DesignDNA, DesignLanguage, EnvironmentDesign
from v365_archviz.domain.workflow import Camera, ViewRole, ViewSet
from v365_archviz.providers.contracts import (
    GeneratedImage,
    GeneratedView,
    GeneratedViewSet,
    ViewConditioningInput,
    ViewSetGenerationInput,
)


class FakeViewSetRenderer:
    name = "fake-viewset"

    def generate(self, request: ViewConditioningInput) -> GeneratedImage:
        raise AssertionError("the view-set use case must not call single-view generation")

    def generate_view_set(self, request: ViewSetGenerationInput) -> GeneratedViewSet:
        buffer = io.BytesIO()
        Image.new("RGB", (16, 9), "green").save(buffer, format="PNG")
        return GeneratedViewSet(
            request_id=request.request_id,
            views=tuple(
                GeneratedView(
                    view_id=view.view_id,
                    image=GeneratedImage(buffer.getvalue(), "image/png", "provider-id"),
                )
                for view in request.views
            ),
        )


def test_refines_an_ordered_view_set_as_one_unit(tmp_path: Path) -> None:
    design = DesignDNA(
        project_id="project",
        design_revision="R01-design",
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
        buildings=(),
        grammar_version="grammar-v1",
        asset_library_version="assets-v1",
    )
    cameras = tuple(
        Camera(
            view_id=f"view-{index:02d}",
            role=role,
            position=(index, index, index),
            target=(0, 0, 0),
            focal_length_mm=35,
            sensor_width_mm=36,
            aspect_ratio="16:9",
        )
        for index, role in ((1, ViewRole.OVERALL), (2, ViewRole.CONTEXT))
    )
    view_set = ViewSet(
        view_set_id="viewset-1",
        design_revision=design.design_revision,
        cameras=cameras,
    )
    design_path = tmp_path / "design.json"
    view_set_path = tmp_path / "views.json"
    design_path.write_text(design.model_dump_json(), encoding="utf-8")
    view_set_path.write_text(view_set.model_dump_json(), encoding="utf-8")
    render_root = tmp_path / "renders"
    for camera in cameras:
        target = render_root / camera.view_id
        target.mkdir(parents=True)
        for name in ("base_rgb", "depth", "instance_id", "semantic", "edges"):
            Image.new("RGB", (16, 9), "white").save(target / f"{name}.png")

    result = RefineViewSet().execute(
        FakeViewSetRenderer(),
        render_root,
        tmp_path / "generated",
        view_set_path,
        design_path,
        "model-revision",
        "prompt",
    )

    assert result.view_count == 2
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["model_revision"] == "model-revision"
    assert manifest["grammar_version"] == "grammar-v1"
    assert [view["view_id"] for view in manifest["views"]] == ["view-01", "view-02"]
