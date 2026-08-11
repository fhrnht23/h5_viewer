"""Диалог пользовательских настроек оформления."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from h5viewer.presentation.qt.theme import ThemeManager
from h5viewer.presentation.qt.translations import tr


class AppearanceSettingsDialog(QDialog):
    """Позволяет сразу оценить и сохранить цветовую схему и стиль Qt."""

    def __init__(self, theme_manager: ThemeManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._theme_manager = theme_manager
        self._initial_dark = theme_manager.dark
        self._initial_style = theme_manager.style_name
        self.setWindowTitle(tr("Settings", "Appearance settings"))
        self.setMinimumWidth(470)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 16)
        layout.setSpacing(14)

        description = QLabel(
            tr(
                "Settings",
                "Choose a color scheme and a Qt widget style. Changes are applied immediately.",
            ),
            self,
        )
        description.setWordWrap(True)
        layout.addWidget(description)

        form = QFormLayout()
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(12)
        self.color_scheme_combo = QComboBox(self)
        self.color_scheme_combo.addItem(tr("Settings", "Light"), False)
        self.color_scheme_combo.addItem(tr("Settings", "Dark"), True)
        self.color_scheme_combo.setCurrentIndex(int(theme_manager.dark))
        form.addRow(tr("Settings", "Color scheme"), self.color_scheme_combo)

        self.style_combo = QComboBox(self)
        self.style_combo.addItems(theme_manager.available_styles())
        style_index = self.style_combo.findText(theme_manager.style_name)
        self.style_combo.setCurrentIndex(max(style_index, 0))
        form.addRow(tr("Settings", "Qt widget style"), self.style_combo)
        layout.addLayout(form)

        preview = QGroupBox(tr("Settings", "Progress preview"), self)
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
            self,
        )
        note.setWordWrap(True)
        layout.addWidget(note)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        self.color_scheme_combo.currentIndexChanged.connect(self._apply_preview)
        self.style_combo.currentIndexChanged.connect(self._apply_preview)

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
