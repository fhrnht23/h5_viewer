"""Интеграционные тесты поиска и порционного сравнения HDF5."""

from __future__ import annotations

import shutil
from pathlib import Path

import h5py
import numpy as np

from h5viewer.domain.models import (
    ComparisonOptions,
    DifferenceKind,
    MetadataField,
    MetadataSearchOptions,
)
from h5viewer.infrastructure.hdf5.analysis import compare_hdf5_files, search_hdf5_metadata


def test_search_finds_paths_dataset_metadata_and_attributes(sample_hdf5: Path) -> None:
    by_path = search_hdf5_metadata(sample_hdf5, MetadataSearchOptions("numeric"))
    by_dtype = search_hdf5_metadata(sample_hdf5, MetadataSearchOptions("float64"))
    by_attribute = search_hdf5_metadata(sample_hdf5, MetadataSearchOptions("м/с"))

    assert any(match.path == "/data/numeric" for match in by_path.matches)
    assert any(match.field is MetadataField.DATASET_METADATA for match in by_dtype.matches)
    assert any(
        match.path == "/data/numeric"
        and match.field is MetadataField.ATTRIBUTE_VALUE
        and match.name == "unit"
        for match in by_attribute.matches
    )
    assert by_path.scanned_links > 10


def test_search_respects_result_limit_and_cancellation(sample_hdf5: Path) -> None:
    limited = search_hdf5_metadata(
        sample_hdf5,
        MetadataSearchOptions("data", max_results=2),
    )
    calls = 0

    def cancelled() -> bool:
        nonlocal calls
        calls += 1
        return calls > 3

    stopped = search_hdf5_metadata(
        sample_hdf5,
        MetadataSearchOptions("data"),
        cancelled=cancelled,
    )

    assert len(limited.matches) == 2
    assert limited.truncated
    assert stopped.cancelled


def test_identical_files_compare_equal(sample_hdf5: Path, tmp_path: Path) -> None:
    copy = tmp_path / "identical.h5"
    shutil.copy2(sample_hdf5, copy)

    report = compare_hdf5_files(sample_hdf5, copy, ComparisonOptions(block_bytes=128))

    assert report.identical
    assert report.compared_objects > 10
    assert report.compared_datasets > 5
    assert report.compared_elements > 60


def test_comparison_finds_structure_attributes_and_chunked_data(
    sample_hdf5: Path,
    tmp_path: Path,
) -> None:
    changed = tmp_path / "changed.h5"
    shutil.copy2(sample_hdf5, changed)
    with h5py.File(changed, "r+") as h5_file:
        h5_file.create_group("only_right")
        h5_file["/data/numeric"].attrs["unit"] = "км/ч"
        h5_file["/data/numeric"][2, 3, 4] = 999.0

    report = compare_hdf5_files(
        sample_hdf5,
        changed,
        ComparisonOptions(block_bytes=64),
    )

    assert any(
        difference.path == "/only_right" and difference.kind is DifferenceKind.ONLY_RIGHT
        for difference in report.differences
    )
    assert any(
        difference.path == "/data/numeric"
        and difference.kind is DifferenceKind.ATTRIBUTE
        and difference.detail == "unit"
        for difference in report.differences
    )
    data_difference = next(
        difference
        for difference in report.differences
        if difference.path in {"/data/numeric", "/numeric_alias"}
        and difference.kind is DifferenceKind.DATA
    )
    assert data_difference.detail == "Index (2, 3, 4)"
    assert data_difference.right_value == "999.0"


def test_float_tolerance_can_ignore_small_data_difference(
    sample_hdf5: Path,
    tmp_path: Path,
) -> None:
    changed = tmp_path / "tolerance.h5"
    shutil.copy2(sample_hdf5, changed)
    with h5py.File(changed, "r+") as h5_file:
        h5_file["/data/numeric"][0, 0, 1] += np.float64(1e-7)

    exact = compare_hdf5_files(sample_hdf5, changed, ComparisonOptions())
    tolerant = compare_hdf5_files(
        sample_hdf5,
        changed,
        ComparisonOptions(absolute_tolerance=1e-6),
    )

    assert any(difference.kind is DifferenceKind.DATA for difference in exact.differences)
    assert all(difference.kind is not DifferenceKind.DATA for difference in tolerant.differences)
