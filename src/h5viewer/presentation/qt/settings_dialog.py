"""Общие настройки оформления и справочник горячих клавиш."""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHeaderView,
    QLabel,
    QProgressBar,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from h5viewer.presentation.qt.theme import ThemeManager
from h5viewer.presentation.qt.translations import tr


class SettingsDialog(QDialog):
    """Настроить оформление и показать фактически назначенные сочетания клавиш."""

    def __init__(
        self,
        theme_manager: ThemeManager,
        shortcuts: Sequence[tuple[str, str]] = (),
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._theme_manager = theme_manager
        self._initial_dark = theme_manager.dark
        self._initial_style = theme_manager.style_name
        self.setWindowTitle(tr("Settings", "Settings"))
        self.setMinimumSize(680, 520)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 16)
        layout.setSpacing(14)

        self.tabs = QTabWidget(self)
        self.tabs.addTab(self._create_appearance_page(), tr("Settings", "Appearance"))
        self.tabs.addTab(
            self._create_shortcuts_page(shortcuts),
            tr("Settings", "Keyboard shortcuts"),
        )
        layout.addWidget(self.tabs, 1)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        self.color_scheme_combo.currentIndexChanged.connect(self._apply_preview)
        self.style_combo.currentIndexChanged.connect(self._apply_preview)

    def _create_appearance_page(self) -> QWidget:
        """Собрать вкладку выбора темы и стиля Qt."""
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 14, 12, 12)
        layout.setSpacing(14)
        description = QLabel(
            tr(
                "Settings",
                "Choose a color scheme and a Qt widget style. Changes are applied immediately.",
            ),
            page,
        )
        description.setWordWrap(True)
        layout.addWidget(description)

        form = QFormLayout()
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(12)
        self.color_scheme_combo = QComboBox(page)
        self.color_scheme_combo.addItem(tr("Settings", "Light"), False)
        self.color_scheme_combo.addItem(tr("Settings", "Dark"), True)
        self.color_scheme_combo.setCurrentIndex(int(self._theme_manager.dark))
        form.addRow(tr("Settings", "Color scheme"), self.color_scheme_combo)

        self.style_combo = QComboBox(page)
        self.style_combo.addItems(self._theme_manager.available_styles())
        style_index = self.style_combo.findText(self._theme_manager.style_name)
        self.style_combo.setCurrentIndex(max(style_index, 0))
        form.addRow(tr("Settings", "Qt widget style"), self.style_combo)
        layout.addLayout(form)

        preview = QGroupBox(tr("Settings", "Progress preview"), page)
        preview_layout = QVBoxLayout(preview)
        preview_layout.setContentsMargins(14, 16, 14, 14)
        preview_layout.setSpacing(8)
        preview_label = QLabel(tr("Settings", "Processing HDF5 objects…"), preview)
        preview_layout.addWidget(preview_label)
        self.progress_preview = QProgressBar(preview)
        self.progress_preview.setRange(0, 100)
        self.progress_preview.setValue(68)
        self.progress_preview.setFormat("68%")
        preview_layout.addWidget(self.progress_preview)
        layout.addWidget(preview)

        note = QLabel(
            tr("Settings", "Cancel restores the previous appearance."),
            page,
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch(1)
        return page

    def _create_shortcuts_page(self, shortcuts: Sequence[tuple[str, str]]) -> QWidget:
        """Собрать неизменяемую таблицу всех активных сочетаний клавиш."""
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 14, 12, 12)
        layout.setSpacing(12)
        description = QLabel(
            tr(
                "Settings",
                "Total Commander-compatible shortcuts are used where the actions match.",
            ),
            page,
        )
        description.setWordWrap(True)
        layout.addWidget(description)

        self.shortcuts_table = QTableWidget(len(shortcuts), 2, page)
        self.shortcuts_table.setObjectName("shortcutsTable")
        self.shortcuts_table.setHorizontalHeaderLabels(
            [tr("Settings", "Action"), tr("Settings", "Shortcut")]
        )
        self.shortcuts_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.shortcuts_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.shortcuts_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.shortcuts_table.setAlternatingRowColors(True)
        self.shortcuts_table.verticalHeader().setVisible(False)
        header = self.shortcuts_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        for row, (action, keys) in enumerate(shortcuts):
            self.shortcuts_table.setItem(row, 0, QTableWidgetItem(action))
            self.shortcuts_table.setItem(row, 1, QTableWidgetItem(keys))
        self.shortcuts_table.resizeRowsToContents()
        layout.addWidget(self.shortcuts_table, 1)
        return page

    def _apply_preview(self, _index: int) -> None:
        """Применить выбранное оформление ко всему приложению без задержки."""
        self._theme_manager.apply(
            dark=bool(self.color_scheme_combo.currentData()),
            style_name=self.style_combo.currentText(),
        )

    def reject(self) -> None:
        """Вернуть оформление, действовавшее до открытия диалога."""
        self._theme_manager.apply(
            dark=self._initial_dark,
            style_name=self._initial_style,
        )
        super().reject()
