import importlib.util
from pathlib import Path
from types import SimpleNamespace

from v365_archviz.application.camera_candidates import CameraCandidate
from v365_archviz.domain.workflow import ViewRole


def test_centred_frontal_elevation_is_not_mistaken_for_two_facades():
    path = Path(__file__).resolve().parents[1] / "scripts/run_camera_search.py"
    spec = importlib.util.spec_from_file_location("camera_search_safety", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    scene = SimpleNamespace(
        elements=[
            SimpleNamespace(
                scene_element_id="building", semantic_role=SimpleNamespace(value="main_shed")
            )
        ],
        surfaces=[
            SimpleNamespace(
                element_id="building",
                frame=SimpleNamespace(normal=normal, origin=(0, 0, 0)),
                width_m=20,
                height_m=10,
            )
            for normal in ((1, 0, 0), (0, 1, 0))
        ],
    )

    def candidate(position):
        return CameraCandidate(
            candidate_id="test",
            role=ViewRole.OVERALL,
            position=position,
            target=(0, 0, 0),
            focal_length_mm=35,
            bearing_deg=0,
            elevation_deg=0,
            distance_m=100,
        )

    assert module._normal_corner_prior(scene, candidate((100, 0, 0))) == 0
    assert module._normal_corner_prior(scene, candidate((100, 100, 0))) == 1
