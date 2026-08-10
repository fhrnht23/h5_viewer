"""Тесты подготовки данных для optional visualization."""

from __future__ import annotations

import numpy as np
import pytest

from h5viewer.presentation.qt import visualization
from h5viewer.presentation.qt.visualization import (
    VisualizationUnavailableError,
    prepare_visualization_data,
)


def test_prepares_vector_as_line_and_matrix_as_heatmap() -> None:
    line = prepare_visualization_data(np.arange(5).reshape(5, 1))
    heatmap = prepare_visualization_data(np.arange(12).reshape(3, 4))

    assert line.mode == "line"
    assert line.values.shape == (5,)
    assert heatmap.mode == "heatmap"
    assert heatmap.values.shape == (3, 4)


def test_complex_values_are_converted_to_magnitude() -> None:
    prepared = prepare_visualization_data(np.array([[3 + 4j, 5 + 12j]]))

    assert prepared.mode == "line"
    assert prepared.complex_magnitude
    np.testing.assert_array_equal(prepared.values, np.array([5.0, 13.0]))


def test_rejects_non_numeric_page() -> None:
    with pytest.raises(VisualizationUnavailableError, match="Only numeric"):
        prepare_visualization_data(np.array([["one", "two"]]))


def test_reports_missing_optional_dependency(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing(_name: str) -> None:
        raise ImportError

    monkeypatch.setattr(visualization.importlib, "import_module", missing)

    with pytest.raises(VisualizationUnavailableError, match="pyqtgraph"):
        visualization.create_visualization_dialog(np.arange(3), "/data/vector")
