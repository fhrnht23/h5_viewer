"""Smoke-тесты Qt без показа окна на экране."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings

from h5viewer.domain.models import DatasetExtent
from h5viewer.presentation.qt.dialogs import DatasetCreationDialog, ResizeDatasetDialog
from h5viewer.presentation.qt.main_window import MainWindow
from h5viewer.presentation.qt.theme import ThemeManager
from h5viewer.presentation.qt.translations import LanguageManager


def test_main_window_defaults_to_russian(qtbot: object, qapp: object) -> None:
    QSettings().clear()
    language = LanguageManager(qapp)  # type: ignore[arg-type]
    language.load()
    theme = ThemeManager(qapp)  # type: ignore[arg-type]
    window = MainWindow(language, theme)
    qtbot.addWidget(window)  # type: ignore[attr-defined]

    assert language.language == "ru"
    assert window.open_action.text() == "Открыть…"
    language.set_language("en")
    assert window.open_action.text() == "Open…"
    language.set_language("ru")


def test_same_document_is_shared_by_both_panes(
    qtbot: object, qapp: object, sample_hdf5: Path
) -> None:
    QSettings().clear()
    language = LanguageManager(qapp)  # type: ignore[arg-type]
    language.load()
    theme = ThemeManager(qapp)  # type: ignore[arg-type]
    window = MainWindow(language, theme)
    qtbot.addWidget(window)  # type: ignore[attr-defined]

    document = window._open_path(sample_hdf5)

    assert document is not None
    assert window.left_pane.session is document
    assert window.right_pane.session is document
    model = window.left_pane._model
    assert model is not None
    assert model.rowCount() == 1
    root_index = model.index(0, 0)
    assert model.data(root_index) == "/"
    if model.canFetchMore(root_index):
        model.fetchMore(root_index)
    assert model.rowCount(root_index) > 5

    root_children = {
        model.data(model.index(row, 0, root_index)): model.index(row, 0, root_index)
        for row in range(model.rowCount(root_index))
    }
    data_index = root_children["data"]
    if model.canFetchMore(data_index):
        model.fetchMore(data_index)
    data_children = {
        model.data(model.index(row, 0, data_index)): model.index(row, 0, data_index)
        for row in range(model.rowCount(data_index))
    }
    alias_index = root_children["numeric_alias"]
    numeric_index = data_children["numeric"]
    alias_link = model.data(alias_index, model.LinkRole)
    model.update_dataset_shape("/data/numeric", alias_link.object_token, (9, 8, 7))
    assert model.data(alias_index.siblingAtColumn(2)) == "(9, 8, 7)"
    assert model.data(numeric_index.siblingAtColumn(2)) == "(9, 8, 7)"


def test_dataset_dialogs_build_typed_requests(qtbot: object, qapp: object) -> None:
    del qapp
    creation = DatasetCreationDialog("/data")
    qtbot.addWidget(creation)  # type: ignore[attr-defined]
    creation.name_edit.setText("created")
    creation.shape_edit.setText("4, 3")
    creation.maxshape_edit.setText("*, 3")
    creation.chunks_edit.setText("2, 3")
    creation.dtype_combo.setCurrentText("float32")
    creation.layout_combo.setCurrentIndex(1)
    creation.compression_combo.setCurrentIndex(1)
    creation.fill_value_edit.setText("1.25")

    request = creation.request()
    assert request.name == "created"
    assert request.options.shape == (4, 3)
    assert request.options.maxshape == (None, 3)
    assert request.options.chunks == (2, 3)
    assert request.options.compression == "gzip"

    resize = ResizeDatasetDialog(DatasetExtent(shape=(4, 3), maxshape=(None, 3), chunks=(2, 3)))
    qtbot.addWidget(resize)  # type: ignore[attr-defined]
    resize.shape_edit.setText("8, 3")
    assert resize.new_shape() == (8, 3)
