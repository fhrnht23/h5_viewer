"""Smoke-тесты Qt без показа окна на экране."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings, Qt

from h5viewer.domain.models import DatasetExtent, LinkKind
from h5viewer.presentation.qt.analysis_dialogs import (
    FileComparisonDialog,
    MetadataSearchDialog,
)
from h5viewer.presentation.qt.dialogs import (
    DatasetCreationDialog,
    LinkCreationDialog,
    ResizeDatasetDialog,
)
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


def test_enter_opens_separate_inspector_and_panels_use_full_window(
    qtbot: object, qapp: object, sample_hdf5: Path
) -> None:
    QSettings().clear()
    language = LanguageManager(qapp)  # type: ignore[arg-type]
    language.load()
    theme = ThemeManager(qapp)  # type: ignore[arg-type]
    window = MainWindow(language, theme)
    qtbot.addWidget(window)  # type: ignore[attr-defined]
    window.show()
    document = window._open_path(sample_hdf5)
    assert document is not None
    assert window.centralWidget() is window.pane_splitter
    assert not window.inspector_window.isVisible()

    model = window.left_pane._model
    assert model is not None
    root_index = model.index(0, 0)
    if model.canFetchMore(root_index):
        model.fetchMore(root_index)
    numeric_alias = next(
        model.index(row, 0, root_index)
        for row in range(model.rowCount(root_index))
        if model.data(model.index(row, 0, root_index)) == "numeric_alias"
    )
    proxy_index = window.left_pane._proxy.mapFromSource(numeric_alias)
    window.left_pane.tree.setCurrentIndex(proxy_index)
    window.left_pane.tree.setFocus()
    qtbot.keyClick(window.left_pane.tree, Qt.Key.Key_Return)  # type: ignore[attr-defined]

    assert window.inspector_window.isVisible()
    assert window._active_link is not None
    assert window._active_link.path == "/numeric_alias"
    assert "shape=(3, 4, 5)" in window.statusBar().currentMessage()
    assert "Enter: открыть инспектор" in window.statusBar().currentMessage()


def test_inspector_shows_rich_metadata_and_opens_reference(
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

    repository = document.repository()
    window._show_object(document, repository.link("/data"))
    assert window.inspector.references_table.rowCount() == 2
    target_row = next(
        row
        for row in range(window.inspector.references_table.rowCount())
        if window.inspector.references_table.item(row, 2).text() == "/data/scalar"
    )
    window.inspector.references_table.selectRow(target_row)
    qtbot.mouseClick(  # type: ignore[attr-defined]
        window.inspector.open_reference_button,
        Qt.MouseButton.LeftButton,
    )
    assert window._active_link is not None
    assert window._active_link.path == "/data/scalar"

    window._show_object(document, repository.link("/data/numeric"))
    assert window.inspector.dimension_scales_table.rowCount() == 3
    assert window.inspector.dimension_scales_table.item(2, 2).text() == "/data/x"
    assert window.inspector.export_dataset_button.isEnabled()
    assert window.inspector.visualize_dataset_button.isEnabled()
    assert window.inspector.export_dataset_button.text() == "Экспорт…"
    assert window.inspector.visualize_dataset_button.text() == "Визуализация…"

    window._show_object(document, repository.link("/data/virtual_numeric"))
    assert window.inspector.virtual_mappings_table.rowCount() == 2


def test_analysis_dialogs_run_and_use_russian_interface(
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
    assert window.search_metadata_action.text() == "Поиск по метаданным…"
    assert window.compare_panes_action.text() == "Сравнить панели…"

    search = MetadataSearchDialog(document)
    qtbot.addWidget(search)  # type: ignore[attr-defined]
    search.query_edit.setText("region_ref")
    search.run_search()
    assert search.report is not None
    assert search.results_table.rowCount() >= 2

    comparison = FileComparisonDialog(document, document)
    qtbot.addWidget(comparison)  # type: ignore[attr-defined]
    comparison.compare_data.setChecked(False)
    comparison.run_comparison()
    assert comparison.report is not None
    assert comparison.report.identical
    assert "совпадают" in comparison.summary_label.text()


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

    link = LinkCreationDialog("/data", Path("/tmp/source.h5"))
    qtbot.addWidget(link)  # type: ignore[attr-defined]
    link.name_edit.setText("external_link")
    link.kind_combo.setCurrentIndex(2)
    link.target_edit.setText("/measurements/signal")
    link.external_file_edit.setText("other.h5")
    link_request = link.request()
    assert link_request.name == "external_link"
    assert link_request.options.link_kind is LinkKind.EXTERNAL
    assert link_request.options.external_file == "other.h5"
