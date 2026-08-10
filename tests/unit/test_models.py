"""Тесты небольших доменных функций."""

from __future__ import annotations

import pytest

from h5viewer.domain.models import (
    default_dataset_slice,
    join_hdf5_path,
    normalize_hdf5_path,
    split_hdf5_path,
)


@pytest.mark.parametrize(
    ("source", "expected"),
    [("", "/"), ("/", "/"), ("data/value", "/data/value"), ("//data//", "/data")],
)
def test_normalize_hdf5_path(source: str, expected: str) -> None:
    assert normalize_hdf5_path(source) == expected


def test_join_and_split_path() -> None:
    assert join_hdf5_path("/data", "value") == "/data/value"
    assert split_hdf5_path("/data/value") == ("/data", "value")


def test_default_dataset_projection() -> None:
    scalar = default_dataset_slice(())
    vector = default_dataset_slice((10,))
    cube = default_dataset_slice((2, 3, 4))
    assert (scalar.row_axis, scalar.column_axis) == (None, None)
    assert (vector.row_axis, vector.column_axis) == (0, None)
    assert (cube.row_axis, cube.column_axis) == (1, 2)
