"""Proofing has to fail loudly, and silence from the model is never a clean bill.

Measured on a real candidate: a frame carrying an orphaned "LO" beside its signage was reported
clean when the whole 2752x1536 image was sent, and reported as a lettering defect when the same
image was proofed in four tiles. The defect is about one percent of the frame width, which is
small enough to be missed and large enough to reach print.
"""

from pathlib import Path

from PIL import Image

from v365_archviz.config import Settings
from v365_archviz.providers.gemini_artefact_judge import ArtefactVerdict, GeminiArtefactJudge


def _verdict(lettering=False, placeholder=False, structure=False) -> ArtefactVerdict:
    return ArtefactVerdict("view-01", lettering, placeholder, structure, "", "", "{}")


def test_malformed_lettering_fails_outright() -> None:
    assert _verdict(lettering=True).status == "fail"


def test_impossible_structure_fails_outright() -> None:
    assert _verdict(structure=True).status == "fail"


def test_a_surviving_placeholder_is_flagged_rather_than_discarded() -> None:
    """It is the one defect a different context policy fixes wholesale, so the image stays in
    play while the policy is what gets reconsidered."""

    assert _verdict(placeholder=True).status == "review"


def test_a_clean_image_passes() -> None:
    assert _verdict().status == "pass"


def test_an_unanswered_question_is_not_a_clean_bill() -> None:
    assert ArtefactVerdict("view-01", None, None, None, "", "", "").status == "unverified"
    assert ArtefactVerdict("view-01", False, None, False, "", "", "").status == "unverified"


def _settings() -> Settings:
    """Reuse the real environment loader so this test never drifts from the Settings signature."""

    import os

    os.environ.setdefault("GEMINI_API_KEY", "test-secret")
    return Settings.from_env()


def test_tiling_asks_about_every_part_of_the_frame(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """A defect in a corner is still in the brochure, so every tile has to be looked at."""

    image = tmp_path / "frame.jpg"
    Image.new("RGB", (400, 200), "white").save(image)
    seen: list[Path] = []

    def _one(_self, view_id: str, path: Path) -> ArtefactVerdict:
        seen.append(path)
        return _verdict()

    monkeypatch.setattr(GeminiArtefactJudge, "_proof_one", _one)
    judge = GeminiArtefactJudge(_settings())

    judge.proof("view-01", image, tiles=4)

    assert len(seen) == 8  # 4 columns x 2 rows
    assert not list(tmp_path.glob(".artefact_tile_*")), "tile scratch files were left behind"


def test_one_bad_tile_condemns_the_image(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    image = tmp_path / "frame.jpg"
    Image.new("RGB", (400, 200), "white").save(image)
    calls: list[int] = []

    def _one(_self, view_id: str, path: Path) -> ArtefactVerdict:
        calls.append(1)
        return _verdict(lettering=True) if len(calls) == 3 else _verdict()

    monkeypatch.setattr(GeminiArtefactJudge, "_proof_one", _one)
    judge = GeminiArtefactJudge(_settings())

    verdict = judge.proof("view-01", image, tiles=4)

    assert verdict.status == "fail"
    # Stops at the first failing tile rather than paying for the rest.
    assert len(calls) == 3


def test_a_single_tile_is_just_the_whole_frame(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    image = tmp_path / "frame.jpg"
    Image.new("RGB", (400, 200), "white").save(image)
    seen: list[Path] = []

    def _one(_self, view_id: str, path: Path) -> ArtefactVerdict:
        seen.append(path)
        return _verdict()

    monkeypatch.setattr(GeminiArtefactJudge, "_proof_one", _one)

    GeminiArtefactJudge(_settings()).proof("view-01", image, tiles=1)

    assert seen == [image]
