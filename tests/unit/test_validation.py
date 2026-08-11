"""Тесты выбора процесса для изолированной проверки HDF5."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from h5viewer.infrastructure.hdf5 import validation


def test_frozen_application_uses_internal_worker_flag(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = tmp_path / "candidate.h5"
    candidate.touch()
    captured: list[list[str]] = []

    def run(command: list[str], **_kwargs: object) -> SimpleNamespace:
        captured.append(command)
        Path(command[3]).write_text(
            '{"object_count": 2, "link_count": 1, "warnings": []}',
            encoding="utf-8",
        )
        return SimpleNamespace(
            returncode=0,
            stdout="",
            stderr="",
        )

    monkeypatch.setattr(validation.sys, "frozen", True, raising=False)
    monkeypatch.setattr(validation.sys, "executable", "/app/H5Viewer")
    monkeypatch.setattr(validation.subprocess, "run", run)

    report = validation.validate_hdf5_in_subprocess(candidate)

    assert captured[0][:3] == ["/app/H5Viewer", "--validate-worker", str(candidate.resolve())]
    assert not Path(captured[0][3]).exists()
    assert report.object_count == 2
    assert report.link_count == 1
