"""Smoke-тесты Qt без показа окна на экране."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings

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
