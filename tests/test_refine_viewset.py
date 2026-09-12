import io
import json
from pathlib import Path

from PIL import Image

from v365_archviz.application.refine_viewset import (
    RefineViewSet,
    _select_master_view_id,
    select_master_view_ids,
)
from v365_archviz.domain.design import DesignDNA, DesignLanguage, EnvironmentDesign
from v365_archviz.domain.workflow import Camera, ViewRole, ViewSet
from v365_archviz.providers.contracts import (
    GeneratedImage,
    GeneratedView,
    GeneratedViewSet,
    ImageProviderCapabilities,
    ViewConditioningInput,
    ViewSetGenerationInput,
)


class FakeViewSetRenderer:
    name = "fake-viewset"
    capabilities = ImageProviderCapabilities(supports_multi_reference=True)

    def __init__(self) -> None:
        self.last_request: ViewSetGenerationInput | None = None

    def generate(self, request: ViewConditioningInput) -> GeneratedImage:
        raise AssertionError("the view-set use case must not call single-view generation")

    def generate_view_set(self, request: ViewSetGenerationInput) -> GeneratedViewSet:
        self.last_request = request
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


def test_selects_a_design_readable_master_instead_of_a_distant_overall(tmp_path: Path) -> None:
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
        for index, role in ((1, ViewRole.OVERALL), (2, ViewRole.DETAIL))
    )
    (tmp_path / "conditioning_qa.json").write_text(
        json.dumps(
            {
                "views": [
                    {
                        "view_id": "view-01",
                        "status": "pass",
                        "focus_coverage": 0.12,
                        "circulation_coverage": 0.03,
                        "context_coverage": 0.04,
                    },
                    {
                        "view_id": "view-02",
                        "status": "pass",
                        "focus_coverage": 0.62,
                        "circulation_coverage": 0.10,
                        "context_coverage": 0.01,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    assert _select_master_view_id(tmp_path, cameras) == "view-02"
    assert select_master_view_ids(tmp_path, cameras) == ("view-01", "view-02")


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
    (tmp_path / "render_intent.json").write_text(
        '{"schema_version":"1.0.0","style_preset":"minimal_industrial"}',
        encoding="utf-8",
    )
    view_set_path.write_text(view_set.model_dump_json(), encoding="utf-8")
    render_root = tmp_path / "renders"
    for camera in cameras:
        target = render_root / camera.view_id
        target.mkdir(parents=True)
        for name in ("base_rgb", "depth", "instance_id", "semantic", "edges"):
            Image.new("RGB", (16, 9), "white").save(target / f"{name}.png")
    Image.new("RGBA", (16, 9), (180, 180, 180, 64)).save(
        render_root / "view-01" / "context_proxy_rgba.png"
    )

    renderer = FakeViewSetRenderer()
    result = RefineViewSet().execute(
        renderer,
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
    assert manifest["generation_strategy"] == "design-master-sequential"
    assert manifest["generated_view_ids"] == ["view-01", "view-02"]
    assert manifest["resumed_from_approved_master"] is False
    assert manifest["master_sha256"]
    assert manifest["render_intent_sha256"]
    identity = json.loads(result.identity_pack_path.read_text(encoding="utf-8"))
    assert identity["master_view_id"] == "view-01"
    assert identity["authority_order"][0] == "current_view_base_geometry"
    assert identity["render_intent_sha256"] == manifest["render_intent_sha256"]
    assert (
        identity["material_role_contract"]["dominant_focus_wall_cladding"]
        == design.material_palette.primary_hex
    )
    assert (
        identity["material_role_contract"]["plinth_structure_eaves_doors_and_docks"]
        == design.material_palette.secondary_hex
    )
    assert (
        identity["material_role_contract"]["continuous_profiled_metal_roof"]
        == design.material_palette.roof_hex
    )
    assert (
        identity["material_role_contract"]["continuous_fence_and_gate"]
        == design.material_palette.boundary_hex
    )
    assert "floating portal" in identity["site_boundary_contract"]["prohibited"]
    assert "invented warehouse" in identity["context_contract"]["prohibited"]
    assert [view["view_id"] for view in manifest["views"]] == ["view-01", "view-02"]
    assert renderer.last_request is not None
    assert "material roles=" in renderer.last_request.identity_prompt
    assert "site boundary family=" in renderer.last_request.identity_prompt
    assert "context policy=" in renderer.last_request.identity_prompt
    assert "PRIMARY VISIBLE FACADE" in renderer.last_request.views[0].prompt
    assert "approved generated loading docks=0" in renderer.last_request.views[0].prompt
    first_references = renderer.last_request.views[0].reference_images
    assert first_references[-1].name == "context_composition_guide.png"
    assert first_references[-1].is_file()
