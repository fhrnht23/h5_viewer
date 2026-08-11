"""Детерминированные проверки ограниченного I/O для огромных логических данных."""

from __future__ import annotations

from pathlib import Path

import h5py

from h5viewer.domain.models import ComparisonOptions
from h5viewer.infrastructure.hdf5.analysis import compare_hdf5_files


def _create_sparse_terabyte(path: Path) -> None:
    """Создать логический массив на 1 ТБ с одним физически выделенным chunk."""
    with h5py.File(path, "w") as h5_file:
        dataset = h5_file.create_dataset(
            "huge",
            shape=(1_000_000, 1_000_000),
            dtype="u1",
            chunks=(64, 64),
            fillvalue=7,
        )
        dataset[900_000, 800_000] = 7


def test_sparse_terabyte_comparison_reads_only_allocated_chunks(tmp_path: Path) -> None:
    left = tmp_path / "huge-left.h5"
    right = tmp_path / "huge-right.h5"
    _create_sparse_terabyte(left)
    _create_sparse_terabyte(right)

    report = compare_hdf5_files(
        left,
        right,
        ComparisonOptions(block_bytes=1024),
    )

    assert report.identical
    assert report.compared_datasets == 1
    assert report.compared_elements == 64 * 64
    assert left.stat().st_size < 1024 * 1024
    assert right.stat().st_size < 1024 * 1024
