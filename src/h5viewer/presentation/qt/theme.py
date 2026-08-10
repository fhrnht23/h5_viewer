"""Светлая и тёмная палитры приложения."""

from __future__ import annotations

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication


class ThemeManager:
    """Применяет компактную современную тему поверх стиля Fusion."""

    def __init__(self, application: QApplication) -> None:
        self._application = application
        self._settings = QSettings()
        self._dark = bool(self._settings.value("ui/dark_theme", False, type=bool))

    @property
    def dark(self) -> bool:
        return self._dark

    def apply(self, dark: bool | None = None) -> None:
        """Применить выбранную палитру и сохранить настройку."""
        if dark is not None:
            self._dark = dark
        self._application.setStyle("Fusion")
        palette = QPalette()
        if self._dark:
            palette.setColor(QPalette.ColorRole.Window, QColor("#1e2228"))
            palette.setColor(QPalette.ColorRole.WindowText, QColor("#e8eaed"))
            palette.setColor(QPalette.ColorRole.Base, QColor("#15181d"))
            palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#242a31"))
            palette.setColor(QPalette.ColorRole.ToolTipBase, QColor("#252b33"))
            palette.setColor(QPalette.ColorRole.ToolTipText, QColor("#f4f4f4"))
            palette.setColor(QPalette.ColorRole.Text, QColor("#e8eaed"))
            palette.setColor(QPalette.ColorRole.Button, QColor("#2b3139"))
            palette.setColor(QPalette.ColorRole.ButtonText, QColor("#e8eaed"))
            palette.setColor(QPalette.ColorRole.BrightText, Qt.GlobalColor.red)
            palette.setColor(QPalette.ColorRole.Highlight, QColor("#2f7dd1"))
            palette.setColor(QPalette.ColorRole.HighlightedText, Qt.GlobalColor.white)
            palette.setColor(QPalette.ColorRole.PlaceholderText, QColor("#9198a1"))
        self._application.setPalette(palette)
        self._application.setStyleSheet(
            """
            QToolBar { spacing: 6px; padding: 4px; }
            QToolButton { padding: 5px 8px; border-radius: 5px; }
            QToolButton:hover { background: rgba(80, 140, 210, 45); }
            QLineEdit, QComboBox, QSpinBox { padding: 5px; border-radius: 5px; }
            QTreeView, QTableView { alternate-background-color: rgba(120, 130, 140, 18); }
            QHeaderView::section {
                padding: 6px;
                border: 0;
                border-bottom: 1px solid rgba(128,128,128,45);
            }
            QTabBar::tab { padding: 7px 12px; }
            """
        )
        self._settings.setValue("ui/dark_theme", self._dark)
