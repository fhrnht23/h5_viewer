"""Инъекция сбоев на границах транзакционного сохранения."""

from __future__ import annotations

from pathlib import Path

import h5py
import pytest

from h5viewer.application import transaction as transaction_module
from h5viewer.application.transaction import TransactionManager
from h5viewer.domain.models import ValidationReport


def _valid_report(_path: Path) -> ValidationReport:
    return ValidationReport(object_count=1, link_count=0)


def test_begin_failure_removes_incomplete_recovery_files(
    sample_hdf5: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = TransactionManager()

    def fail_sync(_path: Path) -> None:
        raise OSError("инъекция сбоя fsync")

    monkeypatch.setattr(transaction_module, "_fsync_file", fail_sync)

    with pytest.raises(OSError, match="инъекция"):
        manager.begin(sample_hdf5)

    assert not tuple(sample_hdf5.parent.glob("*.h5viewer-*.tmp"))
    assert not tuple(sample_hdf5.parent.glob("*.h5viewer-*.recovery.json"))


def test_commit_failure_before_replace_preserves_original_and_recovery(
    sample_hdf5: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = TransactionManager()
    original_bytes = sample_hdf5.read_bytes()
    working = manager.begin(sample_hdf5)
    with h5py.File(working.working_path, "r+") as h5_file:
        h5_file.attrs["pending"] = "изменение рабочей копии"

    def fail_replace(_source: Path, _destination: Path) -> None:
        raise OSError("инъекция сбоя os.replace")

    monkeypatch.setattr(transaction_module.os, "replace", fail_replace)

    with pytest.raises(OSError, match="инъекция"):
        manager.commit(working, _valid_report, create_backup=False)

    assert sample_hdf5.read_bytes() == original_bytes
    assert working.working_path.exists()
    assert working.manifest_path.exists()
    manager.discard(working)


def test_save_as_replace_failure_keeps_destination_and_removes_temporary(
    sample_hdf5: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = tmp_path / "existing.h5"
    original_destination = "не заменять".encode()
    destination.write_bytes(original_destination)

    def fail_replace(_source: Path, _destination: Path) -> None:
        raise OSError("инъекция сбоя os.replace")

    monkeypatch.setattr(transaction_module.os, "replace", fail_replace)

    with pytest.raises(OSError, match="инъекция"):
        TransactionManager().save_as(
            sample_hdf5,
            destination,
            _valid_report,
            create_backup=False,
        )

    assert destination.read_bytes() == original_destination
    assert not tuple(tmp_path.glob("*.h5viewer-save-*.tmp"))
