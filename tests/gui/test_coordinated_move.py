"""GUI-тест связанного undo/redo для межфайлового перемещения."""

from __future__ import annotations

import shutil
from pathlib import Path

import h5py
from PySide6.QtCore import QSettings

from h5viewer.application.commands import CopyObjectCommand, DeleteLinkCommand
from h5viewer.infrastructure.hdf5.copying import copy_hdf5_object
from h5viewer.presentation.qt.main_window import CoordinatedMove, MainWindow
from h5viewer.presentation.qt.theme import ThemeManager
from h5viewer.presentation.qt.translations import LanguageManager


def test_cross_document_move_has_paired_undo_redo(
    qtbot: object,
    qapp: object,
    sample_hdf5: Path,
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "move-source.h5"
    destination_path = tmp_path / "move-destination.h5"
    shutil.copy2(sample_hdf5, source_path)
    with h5py.File(destination_path, "w") as h5_file:
        h5_file.create_group("target")

    QSettings().clear()
    language = LanguageManager(qapp)  # type: ignore[arg-type]
    language.load()
    theme = ThemeManager(qapp)  # type: ignore[arg-type]
    window = MainWindow(language, theme)
    qtbot.addWidget(window)  # type: ignore[attr-defined]
    source = window._open_path(source_path)
    destination = window._open_path(destination_path)
    assert source is not None and destination is not None
    source.begin_edit()
    destination.begin_edit()

    destination_command = CopyObjectCommand(
        source_file=source.active_path,
        source_path="/data/scalar",
        destination_group="/target",
        destination_name="moved",
        copy_operation=copy_hdf5_object,
    )
    source_command = DeleteLinkCommand("/data/scalar")
    destination.execute(destination_command)
    source.execute(source_command)
    window._coordinated_moves.append(
        CoordinatedMove(source, destination, source_command, destination_command)
    )
    window._active_session = destination

    assert destination.repository().read_dataset_value("/target/moved", ()) == 3.5
    assert all(link.name != "scalar" for link in source.repository().list_children("/data", 0, 100))
    window.undo()
    assert source.repository().read_dataset_value("/data/scalar", ()) == 3.5
    assert destination.repository().child_count("/target") == 0

    window.redo()
    assert destination.repository().read_dataset_value("/target/moved", ()) == 3.5
    assert all(link.name != "scalar" for link in source.repository().list_children("/data", 0, 100))
    source.discard()
    destination.discard()
