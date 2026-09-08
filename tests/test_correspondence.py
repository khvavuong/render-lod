import json
from pathlib import Path

from PIL import Image, ImageDraw

from v365_archviz.application.build_correspondence import BuildCorrespondenceIndex
from v365_archviz.domain.scene import CanonicalScene
from v365_archviz.domain.workflow import Camera, ViewRole, ViewSet


def test_builds_visibility_from_instance_identity_pass(
    tmp_path: Path, valid_scene: CanonicalScene
) -> None:
    scene_path = tmp_path / "scene.json"
    scene_path.write_text(valid_scene.model_dump_json(), encoding="utf-8")
    view_set = ViewSet(
        view_set_id="views",
        design_revision="design",
        cameras=(
            Camera(
                view_id="view-01",
                role=ViewRole.OVERALL,
                position=(10, 10, 10),
                target=(0, 0, 0),
                focal_length_mm=35,
                sensor_width_mm=36,
                aspect_ratio="16:9",
            ),
        ),
    )
    view_set_path = tmp_path / "view_set.json"
    view_set_path.write_text(view_set.model_dump_json(), encoding="utf-8")
    view_directory = tmp_path / "renders" / "view-01"
    view_directory.mkdir(parents=True)
    image = Image.new("RGB", (20, 20), (58, 58, 58))
    ImageDraw.Draw(image).rectangle((2, 2, 10, 10), fill=(13, 0, 0))
    image.save(view_directory / "instance_id.png")

    result = BuildCorrespondenceIndex().execute(
        scene_path, view_set_path, tmp_path / "renders"
    )

    assert result.pair_count == 0
    visibility = json.loads(result.visibility_paths[0].read_text(encoding="utf-8"))
    assert visibility["visible_elements"][0]["scene_element_id"] == "shed-1"
