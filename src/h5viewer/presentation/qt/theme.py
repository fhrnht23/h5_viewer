"""Светлая и тёмная визуальные темы приложения."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from PySide6.QtCore import QObject, QSettings, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QProxyStyle,
    QStyle,
    QStyleFactory,
    QStyleOption,
    QWidget,
)


@dataclass(frozen=True, slots=True)
class _ThemeColors:
    """Цветовые токены одной темы без привязки к отдельным виджетам."""

    canvas: str
    surface: str
    surface_alt: str
    surface_hover: str
    border: str
    border_strong: str
    text: str
    text_muted: str
    text_disabled: str
    accent: str
    accent_hover: str
    accent_soft: str
    accent_text: str
    danger: str
    selection: str


_LIGHT = _ThemeColors(
    canvas="#F3F5F9",
    surface="#FFFFFF",
    surface_alt="#F8FAFD",
    surface_hover="#EEF2F8",
    border="#DDE3EC",
    border_strong="#C8D1DE",
    text="#182235",
    text_muted="#68758A",
    text_disabled="#A8B2C0",
    accent="#4169E1",
    accent_hover="#3158CC",
    accent_soft="#E9EEFF",
    accent_text="#FFFFFF",
    danger="#D84A5B",
    selection="#DFE8FF",
)

_DARK = _ThemeColors(
    canvas="#0E131B",
    surface="#151C27",
    surface_alt="#192230",
    surface_hover="#222D3D",
    border="#2A3546",
    border_strong="#3A485D",
    text="#E8EDF6",
    text_muted="#9BA8BB",
    text_disabled="#657185",
    accent="#7292F4",
    accent_hover="#89A4FA",
    accent_soft="#24345F",
    accent_text="#0E1526",
    danger="#FF7381",
    selection="#293F73",
)


class H5ModernStyle(QProxyStyle):
    """Современные размеры элементов поверх стабильного стиля Fusion."""

    NAME = "H5 Modern"
    _METRICS: ClassVar[dict[QStyle.PixelMetric, int]] = {
        QStyle.PixelMetric.PM_DefaultFrameWidth: 1,
        QStyle.PixelMetric.PM_ButtonMargin: 6,
        QStyle.PixelMetric.PM_ScrollBarExtent: 12,
        QStyle.PixelMetric.PM_SmallIconSize: 18,
        QStyle.PixelMetric.PM_ToolBarIconSize: 20,
        QStyle.PixelMetric.PM_ProgressBarChunkWidth: 12,
        QStyle.PixelMetric.PM_LayoutHorizontalSpacing: 8,
        QStyle.PixelMetric.PM_LayoutVerticalSpacing: 8,
    }

    def __init__(self) -> None:
        super().__init__(QStyleFactory.create("Fusion"))
        self.setObjectName("h5-modern")

    def pixelMetric(  # noqa: N802
        self,
        metric: QStyle.PixelMetric,
        option: QStyleOption | None = None,
        widget: QWidget | None = None,
    ) -> int:
        """Вернуть согласованные размеры для часто используемых контролов."""
        if metric in self._METRICS:
            return self._METRICS[metric]
        return super().pixelMetric(metric, option, widget)


class ThemeManager(QObject):
    """Применяет целостную тему и сообщает интерфейсу о её смене."""

    theme_changed = Signal(bool)

    def __init__(self, application: QApplication) -> None:
        super().__init__(application)
        self._application = application
        self._settings = QSettings()
        self._dark = bool(self._settings.value("ui/dark_theme", False, type=bool))
        requested_style = str(
            self._settings.value("ui/widget_style", H5ModernStyle.NAME)
        )
        self._style_name = self._resolve_style_name(requested_style)

    @property
    def dark(self) -> bool:
        return self._dark

    @property
    def style_name(self) -> str:
        """Вернуть имя выбранного базового стиля Qt."""
        return self._style_name

    @staticmethod
    def available_styles() -> tuple[str, ...]:
        """Вернуть собственный стиль первым, затем доступные стили Qt."""
        qt_styles = sorted(QStyleFactory.keys(), key=str.casefold)
        return (H5ModernStyle.NAME, *qt_styles)

    def apply(
        self,
        dark: bool | None = None,
        style_name: str | None = None,
    ) -> None:
        """Применить выбранную палитру и сохранить настройку."""
        if dark is not None:
            self._dark = dark
        if style_name is not None:
            self._style_name = self._resolve_style_name(style_name)
        colors = _DARK if self._dark else _LIGHT
        self._application.setStyle(self._create_style(self._style_name))
        self._application.setFont(self._system_font())
        self._application.setPalette(self._palette(colors))
        self._application.setStyleSheet(self._style_sheet(colors))
        self._settings.setValue("ui/dark_theme", self._dark)
        self._settings.setValue("ui/widget_style", self._style_name)
        self.theme_changed.emit(self._dark)

    @classmethod
    def _resolve_style_name(cls, requested: str) -> str:
        """Найти стиль без учёта регистра или выбрать H5 Modern."""
        return next(
            (
                available
                for available in cls.available_styles()
                if available.casefold() == requested.casefold()
            ),
            H5ModernStyle.NAME,
        )

    @staticmethod
    def _create_style(style_name: str) -> QStyle:
        """Создать новый экземпляр выбранного стиля для QApplication."""
        if style_name == H5ModernStyle.NAME:
            return H5ModernStyle()
        style = QStyleFactory.create(style_name)
        return style if style is not None else H5ModernStyle()

    @staticmethod
    def _system_font() -> QFont:
        """Вернуть системный UI-шрифт с читаемым минимальным размером."""
        font = QFontDatabase.systemFont(QFontDatabase.SystemFont.GeneralFont)
        if font.pointSizeF() < 10.0:
            font.setPointSizeF(10.0)
        return font

    @staticmethod
    def _palette(colors: _ThemeColors) -> QPalette:
        """Собрать полную Qt-палитру, включая неактивные элементы."""
        palette = QPalette()
        palette.setColor(QPalette.ColorRole.Window, QColor(colors.canvas))
        palette.setColor(QPalette.ColorRole.WindowText, QColor(colors.text))
        palette.setColor(QPalette.ColorRole.Base, QColor(colors.surface))
        palette.setColor(QPalette.ColorRole.AlternateBase, QColor(colors.surface_alt))
        palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(colors.surface))
        palette.setColor(QPalette.ColorRole.ToolTipText, QColor(colors.text))
        palette.setColor(QPalette.ColorRole.Text, QColor(colors.text))
        palette.setColor(QPalette.ColorRole.Button, QColor(colors.surface))
        palette.setColor(QPalette.ColorRole.ButtonText, QColor(colors.text))
        palette.setColor(QPalette.ColorRole.BrightText, QColor(colors.danger))
        palette.setColor(QPalette.ColorRole.Highlight, QColor(colors.accent))
        palette.setColor(QPalette.ColorRole.HighlightedText, QColor(colors.accent_text))
        palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(colors.text_muted))
        palette.setColor(QPalette.ColorRole.Mid, QColor(colors.border))
        palette.setColor(QPalette.ColorRole.Dark, QColor(colors.border_strong))
        palette.setColor(
            QPalette.ColorGroup.Disabled,
            QPalette.ColorRole.Text,
            QColor(colors.text_disabled),
        )
        palette.setColor(
            QPalette.ColorGroup.Disabled,
            QPalette.ColorRole.ButtonText,
            QColor(colors.text_disabled),
        )
        return palette

    @staticmethod
    def _style_sheet(colors: _ThemeColors) -> str:
        """Собрать таблицу стилей из токенов выбранной темы."""
        return f"""
            QMainWindow, QDialog {{
                background: {colors.canvas};
                color: {colors.text};
            }}
            QMenuBar {{
                background: {colors.surface};
                border-bottom: 1px solid {colors.border};
                padding: 3px 8px;
            }}
            QMenuBar::item {{
                background: transparent;
                border-radius: 6px;
                padding: 5px 9px;
            }}
            QMenuBar::item:selected {{
                background: {colors.surface_hover};
            }}
            QMenu {{
                background: {colors.surface};
                border: 1px solid {colors.border_strong};
                border-radius: 8px;
                padding: 6px;
            }}
            QMenu::item {{
                border-radius: 5px;
                padding: 7px 28px 7px 10px;
            }}
            QMenu::item:selected {{
                background: {colors.accent_soft};
                color: {colors.text};
            }}
            QMenu::separator {{
                background: {colors.border};
                height: 1px;
                margin: 5px 8px;
            }}
            QToolBar#main_toolbar {{
                background: {colors.surface};
                border: 0;
                border-bottom: 1px solid {colors.border};
                padding: 7px 10px;
                spacing: 4px;
            }}
            QToolBar#main_toolbar QToolButton {{
                background: transparent;
                border: 1px solid transparent;
                border-radius: 7px;
                color: {colors.text};
                min-height: 28px;
                padding: 4px 8px;
            }}
            QToolBar#main_toolbar QToolButton:hover {{
                background: {colors.surface_hover};
                border-color: {colors.border};
            }}
            QToolBar#main_toolbar QToolButton:pressed {{
                background: {colors.accent_soft};
                border-color: {colors.accent};
            }}
            QToolBar#main_toolbar QToolButton:disabled {{
                color: {colors.text_disabled};
            }}
            QToolBar#main_toolbar QToolButton[primary="true"] {{
                background: {colors.accent_soft};
                border-color: {colors.accent_soft};
                color: {colors.accent};
            }}
            QToolBar#main_toolbar QToolButton[primary="true"]:hover {{
                border-color: {colors.accent};
            }}
            QToolBar#main_toolbar QToolButton[compact="true"] {{
                min-width: 28px;
                padding-left: 5px;
                padding-right: 5px;
            }}
            QToolBar#main_toolbar QToolButton[transfer="true"] {{
                color: {colors.text_muted};
                font-size: 11px;
                padding-left: 6px;
                padding-right: 6px;
            }}
            QToolBar#main_toolbar::separator {{
                background: {colors.border};
                width: 1px;
                margin: 6px 7px;
            }}
            QSplitter {{
                background: {colors.canvas};
            }}
            QSplitter::handle {{
                background: transparent;
            }}
            QWidget#browserPane {{
                background: {colors.surface};
                border: 1px solid {colors.border};
                border-radius: 10px;
            }}
            QWidget#browserPane[activePane="true"] {{
                border: 2px solid {colors.accent};
            }}
            QComboBox, QLineEdit, QSpinBox {{
                background: {colors.surface};
                border: 1px solid {colors.border_strong};
                border-radius: 7px;
                color: {colors.text};
                min-height: 24px;
                padding: 4px 8px;
                selection-background-color: {colors.accent};
                selection-color: {colors.accent_text};
            }}
            QComboBox:hover, QLineEdit:hover, QSpinBox:hover {{
                border-color: {colors.text_muted};
            }}
            QComboBox:focus, QLineEdit:focus, QSpinBox:focus {{
                border: 2px solid {colors.accent};
                padding: 3px 7px;
            }}
            QComboBox:disabled, QLineEdit:disabled, QSpinBox:disabled {{
                background: {colors.surface_alt};
                border-color: {colors.border};
                color: {colors.text_disabled};
            }}
            QComboBox::drop-down {{
                border: 0;
                background: transparent;
                width: 24px;
            }}
            QComboBox#documentCombo {{
                background: {colors.surface_alt};
                border-color: {colors.border};
                font-weight: 600;
                min-height: 28px;
                padding-left: 10px;
            }}
            QLineEdit#pathEdit {{
                background: {colors.surface_alt};
                border-color: {colors.border};
                color: {colors.text_muted};
            }}
            QLineEdit#filterEdit {{
                min-height: 28px;
                padding-left: 10px;
            }}
            QPushButton {{
                background: {colors.surface_alt};
                border: 1px solid {colors.border_strong};
                border-radius: 7px;
                color: {colors.text};
                min-height: 26px;
                padding: 4px 12px;
            }}
            QPushButton:hover {{
                background: {colors.surface_hover};
                border-color: {colors.text_muted};
            }}
            QPushButton:pressed {{
                background: {colors.accent_soft};
                border-color: {colors.accent};
            }}
            QPushButton:default {{
                background: {colors.accent};
                border-color: {colors.accent};
                color: {colors.accent_text};
            }}
            QPushButton:default:hover {{
                background: {colors.accent_hover};
            }}
            QPushButton:disabled {{
                background: {colors.surface_alt};
                border-color: {colors.border};
                color: {colors.text_disabled};
            }}
            QGroupBox {{
                border: 1px solid {colors.border};
                border-radius: 8px;
                font-weight: 600;
                margin-top: 10px;
                padding-top: 8px;
            }}
            QGroupBox::title {{
                background: {colors.canvas};
                color: {colors.text_muted};
                left: 10px;
                padding: 0 5px;
                subcontrol-origin: margin;
            }}
            QProgressDialog {{
                min-width: 460px;
            }}
            QProgressDialog QLabel {{
                color: {colors.text};
                min-width: 390px;
                padding: 4px 2px;
            }}
            QProgressBar {{
                background: {colors.surface_alt};
                border: 1px solid {colors.border};
                border-radius: 8px;
                color: {colors.text};
                font-weight: 600;
                min-height: 18px;
                text-align: center;
            }}
            QProgressBar::chunk {{
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 1, y2: 0,
                    stop: 0 {colors.accent_hover}, stop: 1 {colors.accent}
                );
                border: 2px solid {colors.surface_alt};
                border-radius: 7px;
            }}
            QPushButton#rootButton {{
                background: {colors.accent_soft};
                border-color: transparent;
                color: {colors.accent};
                font-weight: 700;
                padding: 3px;
            }}
            QTreeView#objectTree, QTableView, QTableWidget, QTextEdit {{
                background: {colors.surface};
                alternate-background-color: {colors.surface_alt};
                border: 1px solid {colors.border};
                border-radius: 7px;
                gridline-color: {colors.border};
                selection-background-color: {colors.selection};
                selection-color: {colors.text};
            }}
            QTreeView#objectTree {{
                border: 0;
                border-top: 1px solid {colors.border};
                border-radius: 0;
                outline: 0;
            }}
            QTreeView#objectTree::item {{
                border: 0;
                min-height: 28px;
                padding: 2px 5px;
            }}
            QTreeView#objectTree::item:hover {{
                background: {colors.surface_hover};
            }}
            QTreeView#objectTree::item:selected {{
                background: {colors.selection};
                color: {colors.text};
            }}
            QHeaderView {{
                background: {colors.surface_alt};
            }}
            QHeaderView::section {{
                background: {colors.surface_alt};
                border: 0;
                border-bottom: 1px solid {colors.border};
                color: {colors.text_muted};
                font-weight: 600;
                min-height: 28px;
                padding: 4px 7px;
            }}
            QTabWidget::pane {{
                background: {colors.surface};
                border: 1px solid {colors.border};
                border-radius: 8px;
                top: -1px;
            }}
            QTabBar::tab {{
                background: transparent;
                border: 0;
                border-bottom: 2px solid transparent;
                color: {colors.text_muted};
                min-width: 72px;
                padding: 8px 12px;
            }}
            QTabBar::tab:hover {{
                background: {colors.surface_hover};
                color: {colors.text};
            }}
            QTabBar::tab:selected {{
                border-bottom-color: {colors.accent};
                color: {colors.accent};
                font-weight: 600;
            }}
            QScrollBar:vertical {{
                background: transparent;
                border: 0;
                margin: 3px;
                width: 11px;
            }}
            QScrollBar:horizontal {{
                background: transparent;
                border: 0;
                height: 11px;
                margin: 3px;
            }}
            QScrollBar::handle {{
                background: {colors.border_strong};
                border-radius: 4px;
                min-height: 28px;
                min-width: 28px;
            }}
            QScrollBar::handle:hover {{
                background: {colors.text_muted};
            }}
            QScrollBar::add-line, QScrollBar::sub-line,
            QScrollBar::add-page, QScrollBar::sub-page {{
                background: transparent;
                border: 0;
                height: 0;
                width: 0;
            }}
            QStatusBar {{
                background: {colors.surface};
                border-top: 1px solid {colors.border};
                color: {colors.text_muted};
                min-height: 25px;
                padding: 1px 8px;
            }}
            QStatusBar::item {{
                border: 0;
            }}
            QToolTip {{
                background: {colors.surface};
                border: 1px solid {colors.border_strong};
                border-radius: 5px;
                color: {colors.text};
                padding: 5px 7px;
            }}
        """
