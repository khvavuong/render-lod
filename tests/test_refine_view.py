import io
import json
from pathlib import Path

from PIL import Image

from v365_archviz.application.refine_view import PROMPT_VERSION, RefineView
from v365_archviz.providers.contracts import GeneratedImage, ViewConditioningInput


class FakeRenderer:
    name = "fake"

    def generate(self, request: ViewConditioningInput) -> GeneratedImage:
        assert request.view_id == "view-01"
        buffer = io.BytesIO()
        Image.new("RGB", (2, 2), "green").save(buffer, format="PNG")
        return GeneratedImage(
            content=buffer.getvalue(),
            media_type="image/png",
            provider_request_id="request-1",
        )


def test_refines_complete_conditioning_pack_and_writes_manifest(tmp_path: Path) -> None:
    view = tmp_path / "renders" / "view-01"
    view.mkdir(parents=True)
    for name in ("base_rgb.png", "depth.png", "instance_id.png", "edges.png"):
        Image.new("RGB", (2, 2), "white").save(view / name)
    reference = tmp_path / "reference.jpg"
    Image.new("RGB", (2, 2), "blue").save(reference)

    result = RefineView().execute(
        FakeRenderer(),
        tmp_path / "renders",
        "view-01",
        tmp_path / "generated",
        reference_images=(reference,),
    )

    assert result.image_path.is_file()
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["provider"] == "fake"
    assert manifest["prompt_version"] == PROMPT_VERSION
    assert set(manifest["inputs"]) == {
        "base_rgb",
        "depth",
        "instance_id",
        "edges",
        "reference_01",
    }
