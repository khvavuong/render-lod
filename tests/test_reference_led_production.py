import base64
import hashlib
import io
import json
from dataclasses import replace
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from v365_archviz.api import app
from v365_archviz.application.create_generation_job import CreateGenerationJob
from v365_archviz.application.reference_led_input import (
    BRIEF,
    INTENTS,
    REFERENCE_INSTRUCTIONS,
    VERSION,
    proposal_prompt,
    source_envelopes,
)
from v365_archviz.application.run_generation_job import RunGenerationJob, _JobPaths
from v365_archviz.config import Settings
from v365_archviz.domain.workflow import (
    PLANNED_ROLES,
    Camera,
    GenerationProfile,
    ViewRole,
    ViewSet,
    WorkflowState,
)
from v365_archviz.providers.contracts import GeneratedImage, ViewConditioningInput
from v365_archviz.providers.gemini import GeminiImageRenderer
from v365_archviz.providers.local_jobs import LocalJobRepository


def image_bytes():
    buffer = io.BytesIO()
    Image.new("RGB", (16, 9), "white").save(buffer, format="PNG")
    return buffer.getvalue()


def test_proposal_prompt_golden_matches_trial_r1_authority():
    config = json.loads(Path("resource/research/reference_freedom_v1.json").read_text())
    assert config["brief"] == BRIEF
    assert INTENTS["overall"] == config["views"]["aerial"]["intent"]
    assert INTENTS["office_hero"] == config["views"]["office"]["intent"]
    prompt = proposal_prompt([{"role": "main_shed", "maximum_m": [125, 60, 15.1]}], "overall")
    assert "MEASURED SOURCE ENVELOPE" in prompt
    assert "REGISTERED CAMERA" not in prompt
    assert "EXPERIMENTAL PROGRAMME LOCK" not in prompt
    assert "navy" not in prompt


def test_unknown_source_does_not_get_a_guessed_envelope():
    with pytest.raises(ValueError, match="No classified source"):
        source_envelopes({"elements": []})


@pytest.mark.parametrize("role", ["overall", "office_hero"])
def test_vietnam_context_guides_both_purposes_without_fixed_design(role):
    prompt = proposal_prompt([], role, "Retain the existing gate and use ground-level loading.")
    assert "vietnam-industrial-v1" in prompt
    assert "industrial facility in Vietnam" in prompt
    assert "cab-over" in prompt
    assert "left-hand-drive" in prompt
    assert "compact security" in prompt
    assert "not mandatory motifs" in prompt
    assert "do not assume every factory is a distribution centre" in prompt
    assert "Explicit project requirements take precedence" in prompt
    assert "no fixed azimuth, height, lens or corner" in prompt
    assert prompt.endswith("Retain the existing gate and use ground-level loading.")


@pytest.mark.parametrize("policy", [VERSION, "reference-led-registered-v1"])
def test_provider_uses_all_typed_references_without_base_or_legacy_identity(tmp_path, policy):
    ref = tmp_path / "ref.png"
    ref.write_bytes(image_bytes())
    requests = []

    def respond(request):
        requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "outputs": [
                    {
                        "type": "image",
                        "mime_type": "image/png",
                        "data": base64.b64encode(image_bytes()).decode(),
                    }
                ]
            },
        )

    settings = replace(Settings.from_env(), gemini_api_key="test-key")
    roles = tuple(REFERENCE_INSTRUCTIONS)
    instructions = ("architecture", "construction", "context")
    if policy == "reference-led-registered-v1":
        roles += ("approved_design_anchor", "source_geometry_evidence")
        instructions += ("visible design only", "source camera, not programme")
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        renderer = GeminiImageRenderer(settings, client=client)
        renderer.generate(
            ViewConditioningInput(
                view_id="slot",
                base_rgb=tmp_path / "absent",
                depth=ref,
                instance_id=ref,
                semantic=ref,
                edges=ref,
                prompt="Free design proposal",
                generation_policy=policy,
                reference_images=(ref,) * len(roles),
                reference_roles=roles,
                reference_instructions=instructions,
                provider_model="frozen-model",
                image_size="2K",
            )
        )
    payload = requests[0]
    assert payload["model"] == "frozen-model"
    assert payload["store"] is False
    assert len([block for block in payload["input"] if block["type"] == "image"]) == len(roles)
    assert payload["input"][0]["text"] == "Free design proposal"
    assert "BASE RGB" not in json.dumps(payload)


@pytest.fixture
def pilot(tmp_path, monkeypatch):
    monkeypatch.setenv("V365_ARTIFACT_DIR", str(tmp_path))
    scene = tmp_path / "scenes/model/canonical_scene.json"
    scene.parent.mkdir(parents=True)
    scene.write_text("{}")
    references = []
    for role in ("factory_design_reference", "construction_material_reference"):
        path = tmp_path / f"{role}.png"
        path.write_bytes(image_bytes())
        references.append(
            {
                "path": str(path),
                "role": role,
                "instruction": REFERENCE_INSTRUCTIONS[role],
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    spec = {
        "version": VERSION,
        "model": "frozen-model",
        "brief": "",
        "envelopes": [],
        "source_sha256": hashlib.sha256(scene.read_bytes()).hexdigest(),
        "references": references,
        "max_generation_calls": 2,
        "prompts": {role: proposal_prompt([], role) for role in INTENTS},
    }
    view_set = ViewSet(
        view_set_id="views",
        design_revision="design",
        cameras=tuple(
            Camera(
                view_id=f"view-{index:02d}",
                role=role,
                position=(0, 0, 20),
                target=(0, 0, 0),
                focal_length_mm=35,
                sensor_width_mm=36,
                aspect_ratio="16:9",
            )
            for index, role in ((1, ViewRole.OVERALL), (5, ViewRole.OFFICE_HERO))
        ),
    )
    repository = LocalJobRepository(tmp_path / "metadata")
    job = (
        CreateGenerationJob()
        .execute(
            repository,
            project_id="project",
            model_revision="model",
            design_revision="design",
            view_set=view_set,
            profile=GenerationProfile.MARKETING_HERO,
            reference_image_refs=tuple(ref["path"] for ref in references),
            reference_roles=tuple(ref["role"] for ref in references),
            proposal_snapshot=json.dumps(spec),
        )
        .job.transition(WorkflowState.RENDERING_PASSES)
    )
    repository.save(job)
    calls = []

    class Renderer:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def generate(self, request):
            calls.append(request)
            return GeneratedImage(image_bytes(), "image/png", "fake-request")

    monkeypatch.setattr(
        "v365_archviz.application.run_reference_proposal.create_image_renderer",
        lambda *_: Renderer(),
    )
    monkeypatch.setattr(
        RunGenerationJob,
        "_ensure_conditioning",
        lambda *_: pytest.fail("Pilot must not render/lock a procedural facade"),
    )
    return job, repository, replace(Settings.from_env(), artifact_dir=tmp_path), calls


def test_main_flow_stops_at_proposal_and_selection_does_not_generate_delivery(pilot):
    job, repository, settings, calls = pilot
    result = RunGenerationJob().execute(job.job_id, settings)
    assert result.state is WorkflowState.DESIGN_MASTER_REVIEW
    assert len(calls) == 2
    assert all(len(call.reference_images) == 2 for call in calls)
    assert all(not call.base_rgb.exists() for call in calls)
    with TestClient(app) as client:
        response = client.post(f"/v1/view-sets/{result.view_set_id}/approve")
        assert response.status_code == 202
        assert response.json()["proposal_selected"] is True
        assert response.json()["generation_policy"] == VERSION
        assert response.json()["state"] == "design_master_review"
        assert response.json()["certification_state"] == "marketing_generative_review"
        assert client.post(f"/v1/view-sets/{result.view_set_id}/masters/reject").status_code == 409
        outputs = client.get(f"/v1/view-sets/{result.view_set_id}/outputs").json()["outputs"]
        assert len(outputs) == 2
    RunGenerationJob().execute(job.job_id, settings)
    assert len(calls) == 2
    assert repository.get(job.job_id).state is WorkflowState.DESIGN_MASTER_REVIEW


def test_resuming_in_flight_call_does_not_pay_again(pilot):
    job, repository, settings, calls = pilot
    RunGenerationJob().execute(job.job_id, settings)
    paths = _JobPaths.from_job(settings.artifact_dir, job)
    manifest = paths.generated_root / "view-01/generation_manifest.json"
    record = json.loads(manifest.read_text())
    record["status"] = "in_flight"
    manifest.write_text(json.dumps(record))
    repository.save(
        repository.get(job.job_id).model_copy(
            update={
                "state": WorkflowState.GENERATING_VIEWSET,
            }
        )
    )
    result = RunGenerationJob().execute(job.job_id, settings)
    assert result.state is WorkflowState.FAILED
    assert len(calls) == 2


def test_changed_output_invalidates_proposal_selection(pilot):
    job, _, settings, _ = pilot
    RunGenerationJob().execute(job.job_id, settings)
    with TestClient(app) as client:
        assert client.post(f"/v1/view-sets/{job.view_set_id}/approve").status_code == 202
        paths = _JobPaths.from_job(settings.artifact_dir, job)
        (paths.generated_root / "view-01/refined.png").write_bytes(b"changed")
        assert client.get(f"/v1/view-sets/{job.view_set_id}").json()["proposal_selected"] is False
        assert client.post(f"/v1/view-sets/{job.view_set_id}/approve").status_code == 409


def test_changed_reference_fails_before_any_paid_generation(pilot):
    job, _, settings, calls = pilot
    Path(job.reference_image_refs[0]).write_bytes(b"changed reference")
    result = RunGenerationJob().execute(job.job_id, settings)
    assert result.state is WorkflowState.FAILED
    assert not calls


def test_existing_reservation_without_manifest_never_retries(pilot):
    job, _, settings, calls = pilot
    root = _JobPaths.from_job(settings.artifact_dir, job).generated_root / "view-01"
    root.mkdir(parents=True)
    (root / "call_reserved").touch()
    result = RunGenerationJob().execute(job.job_id, settings)
    assert result.state is WorkflowState.FAILED
    assert not calls


def prepare_registered(pilot, monkeypatch):
    from v365_archviz.application.reference_delivery import (
        RegisterDesignRequest,
        SelectShotsRequest,
        register_design,
        select_shots,
    )

    job, repository, settings, calls = pilot
    result = RunGenerationJob().execute(job.job_id, settings)
    paths = _JobPaths.from_job(settings.artifact_dir, result)
    family = register_design(result, paths, RegisterDesignRequest(anchor="site", reviewer="client"))
    rows = []
    for role in PLANNED_ROLES:
        evidence = paths.generated_root / f"evidence-{role.value}.png"
        evidence.write_bytes(image_bytes())
        rows.append(
            {
                "candidate_id": role.value,
                "camera": {"role": role.value},
                "score": 0.8,
                "measurement": {"feasible": True},
                "evidence_ref": str(evidence),
            }
        )
    ranking = paths.generated_root / "shots/ranking.json"
    ranking.parent.mkdir(exist_ok=True)
    ranking.write_text(json.dumps({"candidates": rows}))
    select_shots(result, paths, SelectShotsRequest(candidate_ids=[r.value for r in PLANNED_ROLES]))

    class Renderer:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def generate(self, request):
            calls.append(request)
            return GeneratedImage(image_bytes(), "image/png", "registered-fake")

    monkeypatch.setattr(
        "v365_archviz.application.reference_delivery.create_image_renderer", lambda *_: Renderer()
    )
    repository.save(result.transition(WorkflowState.GENERATING_VIEWSET))
    return job, repository, settings, calls, paths, family


def test_registered_generation_review_and_no_automatic_certification(pilot, monkeypatch):
    job, repository, settings, calls, paths, family = prepare_registered(pilot, monkeypatch)
    result = RunGenerationJob().execute(job.job_id, settings)
    assert result.state is WorkflowState.HUMAN_REVIEW
    assert (
        len(calls) == 8
    )  # Two prior drafts plus six registered calls, never a fresh retry budget.
    assert all(c.generation_policy == "reference-led-registered-v1" for c in calls[2:])
    assert all(len(c.reference_images) == 4 for c in calls[2:])
    assert all(
        c.reference_roles[-2:] == ("approved_design_anchor", "source_geometry_evidence")
        for c in calls[2:]
    )
    qa = json.loads((paths.generated_root / "registered/stage_qa.json").read_text())
    assert qa["consistency"] == "unknown"
    assert qa["geometry_certified"] is False
    assert qa["master_family_id"] == family["master_family_id"]
    review = {
        "reviewer": "human",
        "decision": "approve",
        "evidence_notes": "Reviewed all six outputs against source and shot previews.",
        **{
            k: True
            for k in (
                "realism",
                "architecture",
                "consistency",
                "vietnam_context",
                "source_requirements",
                "camera_fidelity",
            )
        },
    }
    with TestClient(app) as client:
        prefix = f"/v1/view-sets/{job.view_set_id}"
        assert client.post(prefix + "/approve").status_code == 409
        assert (
            client.post(
                prefix + "/delivery-review", json={**review, "consistency": False}
            ).status_code
            == 409
        )
        approved = client.post(prefix + "/delivery-review", json=review)
        assert approved.status_code == 200
        assert approved.json()["geometry_certified"] is False
        assert client.get(prefix).json()["certification_state"] == "marketing_generative_review"
    RunGenerationJob().execute(job.job_id, settings)
    assert len(calls) == 8
    assert repository.get(job.job_id).state is WorkflowState.COMPLETED


def test_registered_anchor_change_and_duplicate_shots_block_calls(pilot, monkeypatch):
    from v365_archviz.application.reference_delivery import SelectShotsRequest, select_shots
    from v365_archviz.errors import V365Error

    job, _, settings, calls, paths, family = prepare_registered(pilot, monkeypatch)
    with pytest.raises(V365Error, match="distinct"):
        select_shots(job, paths, SelectShotsRequest(candidate_ids=["overall"] * 6))
    Path(family["anchor_ref"]).write_bytes(b"changed anchor")
    result = RunGenerationJob().execute(job.job_id, settings)
    assert result.state is WorkflowState.FAILED
    assert len(calls) == 2


def test_registered_reservation_without_manifest_blocks_paid_retry(pilot, monkeypatch):
    job, _, settings, calls, paths, _ = prepare_registered(pilot, monkeypatch)
    folder = paths.generated_root / "registered/view-01"
    folder.mkdir(parents=True)
    (folder / "call_reserved").touch()
    result = RunGenerationJob().execute(job.job_id, settings)
    assert result.state is WorkflowState.FAILED
    assert len(calls) == 2


def test_registered_validation_checkpoint_resumes_without_image_calls(pilot, monkeypatch):
    job, repository, settings, calls, _, _ = prepare_registered(pilot, monkeypatch)
    result = RunGenerationJob().execute(job.job_id, settings)
    repository.save(result.model_copy(update={"state": WorkflowState.VALIDATING}))
    resumed = RunGenerationJob().execute(job.job_id, settings)
    assert resumed.state is WorkflowState.HUMAN_REVIEW
    assert len(calls) == 8


def test_camera_search_adapts_to_site_and_uses_envelope_only(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from v365_archviz.application.reference_shots import search_shots

    seen = []

    class Renderer:
        def execute(self, scene, design, view_set_file, root, profile, **options):
            seen.append(options)
            view_set = ViewSet.model_validate_json(view_set_file.read_text())
            for camera in view_set.cameras:
                folder = root / camera.view_id
                folder.mkdir(parents=True, exist_ok=True)
                (folder / "camera.json").write_text(camera.model_dump_json())
                image = Image.new("RGB", (64, 36), (255, 0, 0))
                image.paste((0, 255, 0), (0, 0, 20, 36))
                image.save(folder / "semantic.png")
                image.save(folder / "base_rgb.png")
                (folder / "semantic_id_manifest.json").write_text(
                    json.dumps(
                        {
                            "roles": [
                                {"semantic_role": "main_shed", "srgb8": [255, 0, 0]},
                                {"semantic_role": "main_entrance", "srgb8": [0, 255, 0]},
                            ]
                        }
                    )
                )

    monkeypatch.setattr(
        "v365_archviz.application.reference_shots.DockerConditioningRenderer", Renderer
    )
    results = []
    for scale in (1, 5):
        root = tmp_path / str(scale)
        root.mkdir()
        scene = root / "scene.json"
        scene.write_text(
            json.dumps(
                {
                    "elements": [
                        {
                            "scene_element_id": "shed",
                            "semantic_role": "main_shed",
                            "bounding_box": {
                                "minimum": [0, 0, 0],
                                "maximum": [40 * scale, 20 * scale, 12],
                            },
                        },
                        {
                            "scene_element_id": "entrance",
                            "semantic_role": "main_entrance",
                            "bounding_box": {"minimum": [0, -4, 0], "maximum": [4, 0, 4]},
                        },
                    ]
                }
            )
        )
        paths = SimpleNamespace(
            scene=scene, design_dna=root / "design.json", generated_root=root / "outputs"
        )
        results.append(
            search_shots(
                paths, SimpleNamespace(view_set_id=f"site-{scale}", design_revision="design")
            )
        )
    assert all(o == {"facade_mode": "envelope_only", "camera_scoring": True} for o in seen)
    assert all(len(r["candidates"]) == 48 for r in results)
    assert (
        results[0]["candidates"][0]["camera"]["position"]
        != results[1]["candidates"][0]["camera"]["position"]
    )
    assert all(r["output_camera_verified"] is False for r in results)
    for result in results:
        hero_cameras = [r["camera"] for r in result["candidates"] if r["camera"]["role"] == "hero"]
        assert all(c["position"][2] == 2.6 for c in hero_cameras)
