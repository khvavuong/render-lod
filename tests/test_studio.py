import json
import math
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from v365_archviz.api import app
from v365_archviz.application.import_scene_upload import (
    ImportSceneUpload,
    context_element_ids,
)
from v365_archviz.application.run_generation_job import _JobPaths
from v365_archviz.application.studio import (
    FinalizeImageSet,
    RegenerateView,
    ShotSpec,
    StartImageSet,
    load_concept_presets,
)
from v365_archviz.application.validate_conditioning import ROLE_TARGETS, ROLE_THRESHOLDS
from v365_archviz.config import Settings
from v365_archviz.domain.design import DesignBrief
from v365_archviz.domain.scene_upload import SceneUpload
from v365_archviz.domain.workflow import ViewRole, ViewSet, WorkflowState
from v365_archviz.errors import InvalidModelError
from v365_archviz.providers.local_jobs import LocalJobRepository

client = TestClient(app)


def _rect(cx: float, cy: float, width: float, depth: float, z: float) -> dict[str, list[float]]:
    xs = (cx - width / 2, cx + width / 2, cx + width / 2, cx - width / 2)
    ys = (cy - depth / 2, cy - depth / 2, cy + depth / 2, cy + depth / 2)
    vertices = [value for x, y in zip(xs, ys, strict=True) for value in (x, y, z)]
    return {"vertices": vertices, "faces": [0, 1, 2, 0, 2, 3]}


def _upload() -> dict[str, object]:
    return {
        "project_id": "project-1",
        "name": "Plant A",
        "buildings": [
            {
                "id": "shed",
                "role": "main_shed",
                "center": [10, 10],
                "width_m": 120,
                "length_m": 70,
                "height_m": 12,
            },
            {
                "id": "office",
                "role": "office_block",
                "center": [-70, -30],
                "width_m": 30,
                "length_m": 18,
                "height_m": 10,
                "rotation_rad": 0.3,
            },
        ],
        "context_buildings": [
            {"id": "n1", "footprint": [[150, 0], [200, 0], [200, 60], [150, 60]], "height_m": 9}
        ],
        "surfaces": [
            {"id": "ground", "role": "site_ground", **_rect(0, 0, 220, 160, 0)},
            {"id": "road", "role": "site_road", **_rect(0, -60, 200, 12, 0.03)},
            {"id": "parking", "role": "parking", **_rect(-70, 40, 50, 40, 0.04)},
            {"id": "green", "role": "landscape_zone", **_rect(80, 55, 40, 30, 0.05)},
        ],
    }


@pytest.fixture
def artifacts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("V365_ARTIFACT_DIR", str(tmp_path))
    return tmp_path


def test_imports_a_site_plan_as_a_canonical_scene(artifacts: Path) -> None:
    imported = ImportSceneUpload().execute(SceneUpload.model_validate(_upload()), artifacts)

    scene = imported.scene
    roles = {element.scene_element_id: element.semantic_role.value for element in scene.elements}
    assert roles["shed"] == "main_shed"
    assert roles["office"] == "office_block"
    assert context_element_ids(scene) == ("context-n1",)
    shed = next(element for element in scene.elements if element.scene_element_id == "shed")
    assert shed.bounding_box.minimum == pytest.approx((-50, -25, 0))
    assert shed.bounding_box.maximum == pytest.approx((70, 45, 12))
    mesh = np.load(imported.scene_path.parent / shed.mesh_ref)
    assert mesh["vertices"].shape == (8, 3)
    assert mesh["faces"].shape == (12, 3)
    shed_faces = sorted(s.surface_id for s in scene.surfaces if s.element_id == "shed")
    assert shed_faces == ["shed:east", "shed:north", "shed:south", "shed:west"]
    south = next(s for s in scene.surfaces if s.surface_id == "shed:south")
    assert south.frame.normal == pytest.approx((0, -1, 0))


def test_the_same_plan_maps_to_the_same_revision(artifacts: Path) -> None:
    first = ImportSceneUpload().execute(SceneUpload.model_validate(_upload()), artifacts)
    again = ImportSceneUpload().execute(SceneUpload.model_validate(_upload()), artifacts)
    moved = _upload()
    moved["buildings"][0]["center"] = [12, 10]  # type: ignore[index]
    changed = ImportSceneUpload().execute(SceneUpload.model_validate(moved), artifacts)

    assert first.created and not again.created
    assert again.model_revision == first.model_revision
    assert changed.model_revision != first.model_revision


def test_scene_endpoint_rejects_broken_meshes(artifacts: Path) -> None:
    upload = _upload()
    upload["surfaces"][0]["faces"] = [0, 1, 9]  # type: ignore[index]

    response = client.post("/v1/scenes", json=upload)

    assert response.status_code == 422


def test_scene_endpoint_requires_the_site_ground(artifacts: Path) -> None:
    upload = _upload()
    upload["surfaces"] = upload["surfaces"][1:]  # type: ignore[index]

    assert client.post("/v1/scenes", json=upload).status_code == 422


def test_every_concept_preset_is_a_valid_brief() -> None:
    presets = load_concept_presets()

    assert [preset.preset_id for preset in presets] == [
        "industrial_park_classic",
        "green_industrial",
        "corporate_identity",
        "tropical_climate",
        "refined_minimal",
    ]
    for preset in presets:
        brief = DesignBrief.model_validate({**preset.brief, "project_id": "p"})
        # The industrial-park context draws estate roads and lots into the conditioning render.
        assert brief.site_design.surrounding_context_mode == "conceptual_industrial_park"


def test_concepts_start_one_single_camera_job_per_preset(artifacts: Path) -> None:
    revision = client.post("/v1/scenes", json=_upload()).json()["model_revision"]

    response = client.post(
        "/v1/studio/concepts", json={"model_revision": revision, "project_id": "project-1"}
    )

    assert response.status_code == 202
    concepts = response.json()["concepts"]
    assert len(concepts) == 5
    assert len({concept["design_revision"] for concept in concepts}) == 5
    repository = LocalJobRepository(artifacts / "metadata")
    heroes = []
    for concept in concepts:
        assert concept["state"] == "rendering_passes"
        job = repository.get_by_view_set(concept["view_set_id"])
        view_set = ViewSet.model_validate_json(job.view_set_snapshot or "")
        assert [camera.view_id for camera in view_set.cameras] == ["view-01"]
        assert view_set.cameras[0].role is ViewRole.OVERALL
        heroes.append(view_set.cameras[0])
        # Vietnamese register and a real park photograph anchor every concept.
        assert job.style_pack_ref and job.style_pack_ref.endswith("vietnam_marketing.json")
        assert job.reference_roles == ("context_realism_reference", "factory_design_reference")
        assert all(Path(ref).is_file() for ref in job.reference_image_refs)
    # Every concept is photographed through the same camera, so they differ only in design.
    assert all(hero == heroes[0] for hero in heroes)

    again = client.post(
        "/v1/studio/concepts", json={"model_revision": revision, "project_id": "project-1"}
    ).json()["concepts"]
    assert [item["created"] for item in again] == [False] * 5
    more = client.post(
        "/v1/studio/concepts",
        json={"model_revision": revision, "project_id": "project-1", "variant": 2},
    ).json()["concepts"]
    assert all(item["created"] for item in more)

    shots = client.get(
        f"/v1/studio/models/{revision}/designs/{concepts[0]['design_revision']}/shots"
    )
    assert shots.status_code == 200
    cameras = shots.json()["cameras"]
    assert [camera["role"] for camera in cameras] == [
        "overall",
        "detail",
        "detail",
        "detail",
        "detail",
        "context",
    ]
    assert [camera["view_id"] for camera in cameras] == [f"view-0{index}" for index in range(1, 7)]
    assert cameras[0]["position"] == pytest.approx(list(heroes[0].position))
    # Five aerials from five different sides, all looking at the concept's target.
    bearings = {
        round(
            math.degrees(
                math.atan2(
                    camera["position"][1] - camera["target"][1],
                    camera["position"][0] - camera["target"][0],
                )
            )
        )
        % 360
        for camera in cameras[:5]
    }
    assert len(bearings) == 5
    assert all(camera["target"] == cameras[0]["target"] for camera in cameras[:5])


def test_every_concept_preset_shares_the_same_daylight() -> None:
    environments = {
        json.dumps(preset.brief["environment"], sort_keys=True) for preset in load_concept_presets()
    }

    assert len(environments) == 1
    assert json.loads(environments.pop())["time"] == "11:30"


def test_orbit_keeps_distance_and_target_and_can_climb() -> None:
    from v365_archviz.application.studio import orbit
    from v365_archviz.domain.workflow import Camera

    camera = Camera(
        view_id="view-01",
        role=ViewRole.OVERALL,
        position=(100.0, 0.0, 50.0),
        target=(0.0, 0.0, 0.0),
        focal_length_mm=28,
        sensor_width_mm=36,
        aspect_ratio="16:9",
    )

    turned = orbit(camera, 90)
    assert turned.position == pytest.approx((0.0, 100.0, 50.0))
    assert turned.target == camera.target

    raised = orbit(camera, 0, pitch_deg=60, distance_scale=1.1)
    distance = math.dist(camera.position, camera.target) * 1.1
    assert math.dist(raised.position, raised.target) == pytest.approx(distance)
    assert raised.position[2] == pytest.approx(distance * math.sin(math.radians(60)))


def test_unknown_scene_is_not_found(artifacts: Path) -> None:
    response = client.post(
        "/v1/studio/concepts", json={"model_revision": "missing", "project_id": "p"}
    )

    assert response.status_code == 404


def _ready_concept(artifacts: Path) -> str:
    revision = client.post("/v1/scenes", json=_upload()).json()["model_revision"]
    concept = client.post(
        "/v1/studio/concepts",
        json={
            "model_revision": revision,
            "project_id": "project-1",
            "preset_ids": ["refined_minimal"],
        },
    ).json()["concepts"][0]
    repository = LocalJobRepository(artifacts / "metadata")
    job = repository.get_by_view_set(concept["view_set_id"])
    paths = _JobPaths.from_job(artifacts, job)
    (paths.generated_root / "view-01").mkdir(parents=True)
    Image.new("RGB", (64, 36), "white").save(paths.generated_root / "view-01" / "refined.jpg")
    job = job.transition(WorkflowState.GENERATING_VIEWSET)
    repository.save(job.transition(WorkflowState.DESIGN_MASTER_REVIEW))
    return str(concept["view_set_id"])


def test_image_set_is_anchored_to_the_chosen_concept(artifacts: Path) -> None:
    concept_id = _ready_concept(artifacts)

    response = client.post(
        "/v1/studio/image-sets",
        json={
            "concept_view_set_id": concept_id,
            "shots": [
                {"position": [-120, -20, 2], "target": [-70, -30, 4], "focal_length_mm": 35},
                {
                    "position": [200, 150, 120],
                    "target": [0, 0, 2],
                    "focal_length_mm": 28,
                    "role": "detail",
                },
            ],
        },
    )

    assert response.status_code == 202
    body = response.json()
    assert body["state"] == "rendering_passes"
    repository = LocalJobRepository(artifacts / "metadata")
    job = repository.get_by_view_set(body["view_set_id"])
    paths = _JobPaths.from_job(artifacts, job)
    view_set = ViewSet.model_validate_json(paths.view_set.read_text())
    assert [(camera.view_id, camera.role.value) for camera in view_set.cameras] == [
        ("view-01", "overall"),
        ("view-02", "custom"),
        ("view-03", "detail"),
    ]
    concept = repository.get_by_view_set(concept_id)
    assert job.reference_image_refs == concept.reference_image_refs
    assert job.style_pack_ref == concept.style_pack_ref
    review = json.loads((paths.generated_root / "design_master_review.json").read_text())
    assert review["approved"] is True
    assert review["view_set_id"] == job.view_set_id
    assert Path(review["master_image_ref"]).is_file()
    assert Path(review["master_image_ref"]).parent == paths.generated_root / "view-01"


def test_image_set_requires_a_ready_concept(artifacts: Path) -> None:
    revision = client.post("/v1/scenes", json=_upload()).json()["model_revision"]
    concept = client.post(
        "/v1/studio/concepts",
        json={
            "model_revision": revision,
            "project_id": "project-1",
            "preset_ids": ["refined_minimal"],
        },
    ).json()["concepts"][0]

    response = client.post(
        "/v1/studio/image-sets",
        json={
            "concept_view_set_id": concept["view_set_id"],
            "shots": [{"position": [0, -100, 2], "target": [0, 0, 4], "focal_length_mm": 35}],
        },
    )

    assert response.status_code == 409


def test_finalize_completes_an_unbranded_set_and_regenerate_reopens_it(artifacts: Path) -> None:
    concept_id = _ready_concept(artifacts)
    settings = Settings.from_env()
    repository = LocalJobRepository(artifacts / "metadata")
    job, _ = StartImageSet().execute(
        settings,
        repository,
        concept_view_set_id=concept_id,
        shots=(ShotSpec(position=(-120, -20, 2), target=(-70, -30, 4), focal_length_mm=35),),
    )
    paths = _JobPaths.from_job(artifacts, job)
    (paths.generated_root / "view-02").mkdir(parents=True)
    Image.new("RGB", (64, 36), "grey").save(paths.generated_root / "view-02" / "refined.jpg")
    for state in (
        WorkflowState.GENERATING_VIEWSET,
        WorkflowState.VALIDATING,
        WorkflowState.HUMAN_REVIEW,
    ):
        job = job.transition(state)
    repository.save(job)
    original = (paths.generated_root / "view-02" / "refined.jpg").read_bytes()

    done = FinalizeImageSet().execute(settings, repository, job.view_set_id)

    assert done.state is WorkflowState.COMPLETED
    assert paths.board.is_file()
    assert (paths.generated_root / "view-02" / "refined.jpg").read_bytes() == original
    review = json.loads((paths.generated_root / "final_viewset_review.json").read_text())
    assert review["approved"] is False

    with pytest.raises(InvalidModelError, match="edit it instead"):
        RegenerateView().execute(settings, repository, job.view_set_id, "view-01")
    reopened = RegenerateView().execute(
        settings, repository, job.view_set_id, "view-02", "brighter"
    )
    assert reopened.state is WorkflowState.REPAIRING
    request = json.loads((paths.generated_root / "manual_repair_request.json").read_text())
    assert request["view_id"] == "view-02"
    assert request["instruction"] == "brighter"


def test_custom_role_has_lenient_checks_and_no_planned_target() -> None:
    assert ROLE_TARGETS[ViewRole.CUSTOM] == frozenset()
    assert ROLE_THRESHOLDS[ViewRole.CUSTOM][0] < ROLE_THRESHOLDS[ViewRole.OVERALL][0]


def test_concept_hero_frames_the_buildings_from_the_planned_bearing(artifacts: Path) -> None:
    from v365_archviz.application.studio import frame_buildings
    from v365_archviz.domain.workflow import Camera

    scene = ImportSceneUpload().execute(SceneUpload.model_validate(_upload()), artifacts).scene
    planned = Camera(
        view_id="view-01",
        role=ViewRole.OVERALL,
        position=(-600.0, -450.0, 380.0),
        target=(0.0, 0.0, 1.0),
        focal_length_mm=28,
        sensor_width_mm=36,
        aspect_ratio="16:9",
    )

    framed = frame_buildings(planned, scene)

    def unit(camera: Camera) -> tuple[float, ...]:
        offset = [p - t for p, t in zip(camera.position, camera.target, strict=True)]
        length = math.sqrt(sum(value * value for value in offset))
        return tuple(value / length for value in offset)

    assert unit(framed) == pytest.approx(unit(planned))
    assert math.dist(framed.position, framed.target) < math.dist(planned.position, planned.target)
    # The rotated office widens the extent: x from -87.0 to 70, y from -43.0 to 45.
    assert framed.target[:2] == pytest.approx((-8.5, 1.0), abs=0.1)

    # An office drawn as a plain box arrives as a utility block and still belongs in the frame.
    upload = _upload()
    upload["buildings"][1]["role"] = "utility_block"  # type: ignore[index]
    plain = ImportSceneUpload().execute(SceneUpload.model_validate(upload), artifacts).scene
    assert frame_buildings(planned, plain).target[:2] == pytest.approx((-8.5, 1.0), abs=0.1)


def test_job_cameras_are_readable(artifacts: Path) -> None:
    concept_id = _ready_concept(artifacts)

    response = client.get(f"/v1/studio/view-sets/{concept_id}/cameras")

    assert response.status_code == 200
    assert [camera["view_id"] for camera in response.json()["cameras"]] == ["view-01"]


def test_unknown_edit_status_is_not_found() -> None:
    assert client.get("/v1/studio/edits/missing").status_code == 404


def test_edits_find_the_views_of_a_namespaced_job(artifacts: Path) -> None:
    from v365_archviz.application.apply_view_edit import view_directory

    concept_id = _ready_concept(artifacts)
    job = LocalJobRepository(artifacts / "metadata").get_by_view_set(concept_id)

    directory = view_directory(Settings.from_env(), job, "view-01")

    # A marketing job writes under its own namespace, not the design's shared folder.
    assert job.output_namespace and job.output_namespace in directory.parts
    assert (directory / "refined.jpg").is_file()
