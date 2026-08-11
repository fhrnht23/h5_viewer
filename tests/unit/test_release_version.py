"""Тесты защиты выпуска от несовпадающих версий."""

from __future__ import annotations

import pytest

from scripts.release_version import release_version


def test_release_tag_matches_package_version() -> None:
    assert release_version("v0.1.0") == "0.1.0"


def test_release_tag_mismatch_is_rejected() -> None:
    with pytest.raises(ValueError, match="Версии релиза не совпадают"):
        release_version("v9.9.9")
