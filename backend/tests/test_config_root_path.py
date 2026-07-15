"""Normalization + validation contract for MYGARAGE_ROOT_PATH (#107)."""

import pytest
from pydantic import ValidationError

from app.config import Settings


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("", ""),
        ("/", ""),
        ("mygarage", "/mygarage"),
        ("/mygarage", "/mygarage"),
        ("/mygarage/", "/mygarage"),
        ("mygarage/", "/mygarage"),
        ("/a/b/", "/a/b"),
    ],
)
def test_root_path_normalization(raw, expected):
    assert Settings(root_path=raw).root_path == expected


@pytest.mark.parametrize(
    "bad",
    [
        "/a?b",
        "/a#b",
        "/a b",
        "/a\\b",
        '/a"b',
        "/..",
        "/a/../b",
        "/.",
    ],
)
def test_root_path_rejects_unsafe_input(bad):
    # Interpolated into <base href> + URLs, so reject non-path syntax (Codex R1-F2).
    with pytest.raises(ValidationError):
        Settings(root_path=bad)
