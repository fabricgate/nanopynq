from pathlib import Path

import pytest

from nanopynq import Overlay
from nanopynq.resolve import resolve_design


def test_resolve_bundled_camera_design():
    d = resolve_design("camera", "tangnano4k")
    assert d.name == "tangnano4k-camera" and (d / "manifest.yaml").is_file()


def test_base_still_resolves():
    assert resolve_design("base", "tangnano9k").name == "tangnano9k-base"


def test_unknown_bundled_name_is_treated_as_path():
    assert resolve_design("nope", "tangnano4k") == Path("nope")


def test_bundled_name_without_board_lists_boards():
    with pytest.raises(ValueError, match="tangnano4k"):
        Overlay("camera")
