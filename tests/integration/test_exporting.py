"""Интеграционные тесты атомарного экспорта datasets."""

from __future__ import annotations

import csv
from pathlib import Path

import numpy as np
import pytest

from h5viewer.domain.errors import ExportError
from h5viewer.domain.models import (
    DatasetExportOptions,
    DatasetSlice,
    ExportFormat,
)
from h5viewer.infrastructure.hdf5.exporting import export_hdf5_dataset


def test_exports_full_dataset_to_npy_in_small_blocks(
    sample_hdf5: Path,
    tmp_path: Path,
) -> None:
    destination = tmp_path / "numeric.npy"

    report = export_hdf5_dataset(
        sample_hdf5,
        "/data/numeric",
        destination,
        DatasetExportOptions(ExportFormat.NPY, block_bytes=32),
    )

    values = np.load(destination, allow_pickle=False)
    np.testing.assert_array_equal(values, np.arange(60, dtype=np.float64).reshape(3, 4, 5))
    assert report.exported_elements == 60
    assert report.total_elements == 60
    assert report.written_bytes == destination.stat().st_size


def test_exports_full_selected_projection_to_csv(
    sample_hdf5: Path,
    tmp_path: Path,
) -> None:
    destination = tmp_path / "projection.csv"
    selection = DatasetSlice(
        row_axis=1,
        column_axis=2,
        fixed_indices=(2, 0, 0),
        row_offset=3,
        column_offset=4,
    )

    report = export_hdf5_dataset(
        sample_hdf5,
        "/data/numeric",
        destination,
        DatasetExportOptions(ExportFormat.CSV, selection=selection, block_bytes=48),
    )

    with destination.open(encoding="utf-8", newline="") as stream:
        rows = [[float(value) for value in row] for row in csv.reader(stream)]
    np.testing.assert_array_equal(rows, np.arange(40.0, 60.0).reshape(4, 5))
    assert report.exported_elements == 20
    assert report.total_elements == 20


def test_csv_resolves_reference_values(sample_hdf5: Path, tmp_path: Path) -> None:
    destination = tmp_path / "references.csv"

    export_hdf5_dataset(
        sample_hdf5,
        "/data/object_refs",
        destination,
        DatasetExportOptions(ExportFormat.CSV),
    )

    with destination.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.reader(stream))
    assert rows[0] == ["/data/scalar"]
    assert rows[1][0] in {"/data/numeric", "/numeric_alias"}
    assert rows[2] == ["NULL"]


def test_cancelled_export_preserves_existing_destination(
    sample_hdf5: Path,
    tmp_path: Path,
) -> None:
    destination = tmp_path / "existing.csv"
    destination.write_text("исходное содержимое", encoding="utf-8")

    report = export_hdf5_dataset(
        sample_hdf5,
        "/data/numeric",
        destination,
        DatasetExportOptions(ExportFormat.CSV, block_bytes=32),
        cancelled=lambda: True,
    )

    assert report.cancelled
    assert destination.read_text(encoding="utf-8") == "исходное содержимое"


def test_unsupported_npy_export_preserves_existing_destination(
    sample_hdf5: Path,
    tmp_path: Path,
) -> None:
    destination = tmp_path / "existing.npy"
    destination.write_bytes(b"original")

    with pytest.raises(ExportError, match="object, vlen or reference"):
        export_hdf5_dataset(
            sample_hdf5,
            "/data/unicode_strings",
            destination,
            DatasetExportOptions(ExportFormat.NPY),
        )

    assert destination.read_bytes() == b"original"
