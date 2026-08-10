"""Опциональная визуализация ограниченной страницы numeric dataset."""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Any

import numpy as np
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from h5viewer.presentation.qt.translations import tr


class VisualizationUnavailableError(RuntimeError):
    """Графический backend не установлен или данные нельзя отобразить."""


@dataclass(frozen=True, slots=True)
class VisualizationData:
    """Подготовленные числовые данные без зависимости от pyqtgraph."""

    values: np.ndarray[Any, Any]
    mode: str
    complex_magnitude: bool = False


def prepare_visualization_data(values: np.ndarray[Any, Any]) -> VisualizationData:
    """Преобразовать небольшую страницу в line или heatmap representation."""
    array = np.asarray(values)
    if array.size == 0:
        raise VisualizationUnavailableError("Dataset page is empty")
    if array.dtype.fields is not None or array.dtype.kind not in {"b", "i", "u", "f", "c"}:
        raise VisualizationUnavailableError("Only numeric dataset pages can be visualized")
    complex_magnitude = array.dtype.kind == "c"
    numeric = np.abs(array) if complex_magnitude else array
    numeric = np.asarray(numeric, dtype=np.float64)
    if numeric.ndim == 0 or (numeric.ndim <= 2 and 1 in numeric.shape):
        return VisualizationData(numeric.reshape(-1), "line", complex_magnitude)
    if numeric.ndim == 1:
        return VisualizationData(numeric, "line", complex_magnitude)
    if numeric.ndim == 2:
        return VisualizationData(numeric, "heatmap", complex_magnitude)
    raise VisualizationUnavailableError("Visualization expects a one- or two-dimensional page")


def create_visualization_dialog(
    values: np.ndarray[Any, Any],
    dataset_path: str,
    parent: QWidget | None = None,
) -> QDialog:
    """Создать диалог pyqtgraph после ленивой проверки optional dependency."""
    data = prepare_visualization_data(values)
    try:
        pg: Any = importlib.import_module("pyqtgraph")
    except ImportError as exc:
        raise VisualizationUnavailableError(
            "pyqtgraph is not installed; install the 'plots' extra"
        ) from exc

    dialog = QDialog(parent)
    dialog.setWindowTitle(tr("Visualization", "Dataset visualization"))
    layout = QVBoxLayout(dialog)
    description = tr("Visualization", "Current page: {shape}").format(
        shape=" × ".join(str(size) for size in np.asarray(values).shape)
    )
    if data.complex_magnitude:
        description += f" · {tr('Visualization', 'Magnitude of complex values')}"
    label = QLabel(f"{dataset_path} · {description}", dialog)
    layout.addWidget(label)

    if data.mode == "line":
        plot = pg.PlotWidget(dialog)
        plot.showGrid(x=True, y=True, alpha=0.25)
        plot.plot(
            np.arange(data.values.size),
            data.values,
            pen=pg.mkPen("#2f80ed", width=2),
            symbol="o" if data.values.size <= 200 else None,
            symbolSize=5,
        )
        layout.addWidget(plot, 1)
    else:
        image_view = pg.ImageView(dialog)
        image_view.setImage(data.values, autoLevels=True)
        layout.addWidget(image_view, 1)

    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, dialog)
    close_button = buttons.button(QDialogButtonBox.StandardButton.Close)
    if close_button is not None:
        close_button.setText(tr("Visualization", "Close"))
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    dialog.resize(900, 620)
    return dialog
