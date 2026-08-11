"""Композиция и запуск Qt-приложения."""

from __future__ import annotations

import sys
from collections.abc import Sequence
from typing import cast

from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from h5viewer import __version__
from h5viewer.plugins.loader import PluginManager
from h5viewer.presentation.qt.main_window import MainWindow
from h5viewer.presentation.qt.platform import prepare_qt_platform_plugins
from h5viewer.presentation.qt.theme import ThemeManager
from h5viewer.presentation.qt.translations import LanguageManager


def create_application(arguments: Sequence[str] | None = None) -> tuple[QApplication, MainWindow]:
    """Создать приложение и окно без запуска цикла событий, что удобно для тестов."""
    prepare_qt_platform_plugins()
    QCoreApplication.setOrganizationName("H5Viewer")
    QCoreApplication.setOrganizationDomain("h5viewer.local")
    QCoreApplication.setApplicationName("H5 Viewer")
    QCoreApplication.setApplicationVersion(__version__)
    instance = QApplication.instance()
    application = (
        cast(QApplication, instance)
        if instance is not None
        else QApplication(list(arguments or []))
    )
    application.setAttribute(Qt.ApplicationAttribute.AA_DontShowIconsInMenus, False)
    application.setWindowIcon(QIcon())
    language = LanguageManager(application)
    language.load()
    theme = ThemeManager(application)
    theme.apply()
    window = MainWindow(language, theme)
    window.install_plugins(PluginManager())
    # Менеджеры принадлежат приложению логически, но окно удерживает Python-ссылки на них.
    return application, window


def run(arguments: Sequence[str] | None = None) -> int:
    """Показать главное окно и запустить цикл обработки событий."""
    application, window = create_application(arguments or sys.argv)
    window.show()
    return application.exec()
