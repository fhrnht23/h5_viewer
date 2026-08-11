"""Тесты безопасного редактирования и транзакционного сохранения."""

from __future__ import annotations

import shutil
from pathlib import Path

import h5py
import numpy as np
import pytest

from h5viewer.application.commands import (
    CopyObjectCommand,
    CreateDatasetCommand,
    CreateLinkCommand,
    DeleteAttributeCommand,
    DeleteLinkCommand,
    ResizeDatasetCommand,
    SetAttributeCommand,
    WriteDatasetValueCommand,
)
from h5viewer.application.document import DocumentSession
from h5viewer.domain.errors import SaveConflictError
from h5viewer.domain.models import (
    DatasetCreationOptions,
    LinkCreationOptions,
    LinkKind,
    default_dataset_slice,
)
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


def test_dataset_creation_and_resize_are_undoable(sample_hdf5: Path, tmp_path: Path) -> None:
    path = tmp_path / "dataset-commands.h5"
    shutil.copy2(sample_hdf5, path)
    session = _session(path)
    session.begin_edit()
    options = DatasetCreationOptions(
        shape=(2, 2),
        dtype="int32",
        maxshape=(None, 2),
        chunked=True,
        fill_value_text="7",
    )

    session.execute(CreateDatasetCommand("/data", "command_created", options))
    assert session.repository().dataset_extent("/data/command_created").shape == (2, 2)
    session.undo()
    assert "command_created" not in {
        link.name for link in session.repository().list_children("/data", 0, 100)
    }
    session.redo()

    session.execute(ResizeDatasetCommand("/data/command_created", (4, 2)))
    assert session.repository().dataset_extent("/data/command_created").shape == (4, 2)
    session.undo()
    assert session.repository().dataset_extent("/data/command_created").shape == (2, 2)
    session.redo()
    assert session.repository().read_dataset_value("/data/command_created", (3, 1)) == 7
    result = session.save(create_backup=False)
    assert result is not None
    with h5py.File(path, "r") as saved:
        dataset = saved["/data/command_created"]
        assert dataset.shape == (4, 2)
        assert dataset.maxshape == (None, 2)
        assert dataset[3, 1] == 7


def test_dataset_shrink_snapshot_restores_discarded_data(
    sample_hdf5: Path,
    tmp_path: Path,
) -> None:
    path = tmp_path / "dataset-shrink.h5"
    shutil.copy2(sample_hdf5, path)
    session = _session(path)
    session.begin_edit()
    original_values = np.arange(60, dtype=np.float64).reshape(3, 4, 5)

    session.execute(ResizeDatasetCommand("/data/numeric", (2, 3, 4)))
    assert session.repository().dataset_extent("/data/numeric").shape == (2, 3, 4)
    np.testing.assert_array_equal(
        session.repository()
        .read_dataset_page(
            "/data/numeric",
            default_dataset_slice((2, 3, 4)),
        )
        .values,
        original_values[0, :3, :4],
    )
    assert len(tuple(tmp_path.glob("*.h5viewer-resize-undo"))) == 1

    session.undo()
    assert session.repository().dataset_extent("/data/numeric").shape == (3, 4, 5)
    with h5py.File(session.active_path, "r") as restored:
        np.testing.assert_array_equal(restored["/data/numeric"][...], original_values)
    assert not tuple(tmp_path.glob("*.h5viewer-resize-undo"))

    session.redo()
    assert session.repository().dataset_extent("/numeric_alias").shape == (2, 3, 4)
    assert len(tuple(tmp_path.glob("*.h5viewer-resize-undo"))) == 1
    result = session.save(create_backup=False)
    assert result is not None
    assert not tuple(tmp_path.glob("*.h5viewer-resize-undo"))
    with h5py.File(path, "r") as saved:
        assert saved["/data/numeric"].shape == (2, 3, 4)


def test_link_creation_and_deletion_are_undoable(sample_hdf5: Path, tmp_path: Path) -> None:
    path = tmp_path / "link-commands.h5"
    shutil.copy2(sample_hdf5, path)
    session = _session(path)
    session.begin_edit()

    session.execute(
        CreateLinkCommand(
            "/data",
            "soft_command",
            LinkCreationOptions(LinkKind.SOFT, "/missing/target"),
        )
    )
    assert any(
        link.name == "soft_command" for link in session.repository().list_children("/data", 0, 100)
    )
    session.undo()
    assert all(
        link.name != "soft_command" for link in session.repository().list_children("/data", 0, 100)
    )
    session.redo()

    alias_token = next(
        link.object_token
        for link in session.repository().list_children("/data", 0, 100)
        if link.name == "numeric"
    )
    session.execute(DeleteLinkCommand("/numeric_alias"))
    session.undo()
    restored_alias = next(
        link
        for link in session.repository().list_children("/", 0, 100)
        if link.name == "numeric_alias"
    )
    assert restored_alias.object_token == alias_token

    session.execute(DeleteLinkCommand("/data/scalar"))
    undo_files = tuple(path.parent.glob("*.h5viewer-undo"))
    assert len(undo_files) == 1
    session.undo()
    assert session.repository().read_dataset_value("/data/scalar", ()) == 3.5

    session.execute(DeleteLinkCommand("/loops"))
    session.undo()
    loops_link = next(
        link for link in session.repository().list_children("/", 0, 100) if link.name == "loops"
    )
    self_link = session.repository().list_children("/loops", 0, 10)[0]
    assert self_link.object_token == loops_link.object_token
    session.discard()
    assert not tuple(path.parent.glob("*.h5viewer-undo"))
