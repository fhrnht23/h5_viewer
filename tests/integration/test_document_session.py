"""Тесты безопасного редактирования и транзакционного сохранения."""

from __future__ import annotations

import shutil
from pathlib import Path

import h5py
import pytest

from h5viewer.application.commands import (
    CopyObjectCommand,
    DeleteAttributeCommand,
    SetAttributeCommand,
    WriteDatasetValueCommand,
)
from h5viewer.application.document import DocumentSession
from h5viewer.domain.errors import SaveConflictError
from h5viewer.infrastructure.hdf5.copying import copy_hdf5_object
from h5viewer.infrastructure.hdf5.h5py_repository import H5pyRepository


def _session(path: Path) -> DocumentSession:
    return DocumentSession(
        path,
        lambda file_path, writable: H5pyRepository(file_path, writable=writable),
    )


def test_original_remains_unchanged_until_save(sample_hdf5: Path, tmp_path: Path) -> None:
    path = tmp_path / "editing.h5"
    shutil.copy2(sample_hdf5, path)
    session = _session(path)
    session.begin_edit()
    session.execute(WriteDatasetValueCommand("/data/numeric", (0, 0, 0), "99.5"))

    with h5py.File(path, "r") as original:
        assert original["/data/numeric"][0, 0, 0] == 0.0
    assert session.repository().read_dataset_value("/data/numeric", (0, 0, 0)) == 99.5

    session.undo()
    assert session.repository().read_dataset_value("/data/numeric", (0, 0, 0)) == 0.0
    session.redo()
    result = session.save()

    assert result is not None
    assert result.backup_path is not None and result.backup_path.exists()
    with h5py.File(path, "r") as saved:
        assert saved["/data/numeric"][0, 0, 0] == 99.5


def test_attribute_delete_can_be_undone_with_original_dtype(
    sample_hdf5: Path, tmp_path: Path
) -> None:
    path = tmp_path / "attribute.h5"
    shutil.copy2(sample_hdf5, path)
    session = _session(path)
    session.begin_edit()
    session.execute(DeleteAttributeCommand("/data/numeric", "unit"))
    session.undo()
    snapshot = session.repository().read_attribute_value("/data/numeric", "unit")
    assert snapshot.value == "м/с"

    session.execute(SetAttributeCommand("/data/numeric", "new_value", "[1, 2, 3]"))
    session.undo()
    names = {
        attribute.name for attribute in session.repository().details("/data/numeric").attributes
    }
    assert "new_value" not in names
    session.discard()


def test_external_change_blocks_commit(sample_hdf5: Path, tmp_path: Path) -> None:
    path = tmp_path / "conflict.h5"
    shutil.copy2(sample_hdf5, path)
    session = _session(path)
    session.begin_edit()
    session.execute(WriteDatasetValueCommand("/data/scalar", (), "8"))

    with h5py.File(path, "r+") as external_writer:
        external_writer.attrs["outside"] = 1
        external_writer.flush()

    with pytest.raises(SaveConflictError):
        session.save()
    with h5py.File(path, "r") as original:
        assert original["/data/scalar"][()] == 3.5
        assert original.attrs["outside"] == 1
    session.discard()


def test_discard_removes_working_copy(sample_hdf5: Path, tmp_path: Path) -> None:
    path = tmp_path / "discard.h5"
    shutil.copy2(sample_hdf5, path)
    session = _session(path)
    session.begin_edit()
    working_path = session.active_path
    assert working_path.exists()
    session.discard()
    assert not working_path.exists()
    assert session.active_path == path


def test_copy_between_documents_is_undoable(sample_hdf5: Path, tmp_path: Path) -> None:
    source = tmp_path / "copy-source.h5"
    destination = tmp_path / "copy-destination.h5"
    shutil.copy2(sample_hdf5, source)
    with h5py.File(destination, "w") as h5_file:
        h5_file.create_group("target")
    session = _session(destination)
    session.begin_edit()
    command = CopyObjectCommand(
        source_file=source,
        source_path="/data/numeric",
        destination_group="/target",
        destination_name="copied",
        copy_operation=copy_hdf5_object,
    )
    session.execute(command)
    assert session.repository().details("/target/copied").kind.value == "dataset"
    session.undo()
    assert session.repository().child_count("/target") == 0
    session.redo()
    assert session.repository().details("/target/copied").kind.value == "dataset"
    session.discard()


def test_copy_preserves_indirect_links(sample_hdf5: Path, tmp_path: Path) -> None:
    destination = tmp_path / "links-destination.h5"
    with h5py.File(destination, "w") as h5_file:
        h5_file.create_group("target")

    for source_name in ("soft_numeric", "broken_soft", "external"):
        copy_hdf5_object(sample_hdf5, f"/{source_name}", destination, "/target", source_name)

    with h5py.File(destination, "r") as h5_file:
        soft_link = h5_file["/target"].get("soft_numeric", getlink=True)
        broken_link = h5_file["/target"].get("broken_soft", getlink=True)
        external_link = h5_file["/target"].get("external", getlink=True)
        assert isinstance(soft_link, h5py.SoftLink)
        assert soft_link.path == "/data/numeric"
        assert isinstance(broken_link, h5py.SoftLink)
        assert broken_link.path == "/missing/object"
        assert isinstance(external_link, h5py.ExternalLink)
        assert external_link.path == "/external_data"
