"""An edited view keeps its url, so the browser has to be told to ask again.

Editing a view rewrites its `refined.*` in place and the asset id names the
view, not the file, so the same address serves different bytes afterwards. With
no cache directive the browser decided for itself how long the old picture
stayed fresh — and an edit that had been generated, committed and written to
disk went on being drawn from the cache, which is indistinguishable from an edit
that was thrown away.

`no-cache` does not forbid the cache, it requires the question. The reply has to
exist too: Starlette does not answer a conditional request for a `FileResponse`,
so without it every page view would re-download every image in full.
"""

from __future__ import annotations

from pathlib import Path

from v365_archviz.api import _etag, _matches


def written(path: Path, content: bytes) -> Path:
    path.write_bytes(content)
    return path


class TestValidator:
    def test_the_same_file_keeps_its_validator(self, tmp_path: Path) -> None:
        image = written(tmp_path / "refined.png", b"first")
        assert _etag(image) == _etag(image)

    def test_an_edited_file_gets_a_new_one(self, tmp_path: Path) -> None:
        image = written(tmp_path / "refined.png", b"first")
        before = _etag(image)
        written(image, b"second, and a different length")
        assert _etag(image) != before

    def test_the_validator_is_quoted_as_the_protocol_requires(self, tmp_path: Path) -> None:
        etag = _etag(written(tmp_path / "refined.png", b"first"))
        assert etag.startswith('"') and etag.endswith('"')


class TestMatching:
    def test_a_browser_holding_this_version_is_recognised(self) -> None:
        assert _matches('"abc"', '"abc"') is True

    def test_a_browser_holding_another_version_is_not(self) -> None:
        assert _matches('"abc"', '"def"') is False

    def test_a_first_visit_sends_nothing_and_matches_nothing(self) -> None:
        assert _matches(None, '"abc"') is False
        assert _matches("", '"abc"') is False

    def test_one_of_several_held_versions_is_enough(self) -> None:
        assert _matches('"old", "abc"', '"abc"') is True

    def test_a_weak_validator_still_names_the_same_bytes(self) -> None:
        # Proxies may weaken a validator in transit; it still identifies the
        # version, and re-sending two megabytes because of the prefix helps
        # nobody.
        assert _matches('W/"abc"', '"abc"') is True

    def test_a_browser_that_will_take_anything_it_has_is_answered(self) -> None:
        assert _matches("*", '"abc"') is True
