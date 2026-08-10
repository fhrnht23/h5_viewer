"""Общие pytest-fixtures с программно созданными HDF5-файлами."""

from __future__ import annotations

from pathlib import Path

import h5py
import numpy as np
import pytest

from h5viewer.presentation.qt.platform import prepare_qt_platform_plugins

# pytest-qt создаёт QApplication раньше GUI-тестов, поэтому подготавливаем Qt заранее.
prepare_qt_platform_plugins()


@pytest.fixture
def sample_hdf5(tmp_path: Path) -> Path:
    """Создать небольшой файл с разными объектами, ссылками и типами."""
    external_path = tmp_path / "external.h5"
    with h5py.File(external_path, "w") as external:
        external.create_dataset("external_data", data=np.arange(6).reshape(2, 3))

    path = tmp_path / "sample.h5"
    enum_dtype = h5py.enum_dtype({"OFF": 0, "ON": 1}, basetype="u1")
    compound_dtype = np.dtype([("id", "<i4"), ("value", "<f8")])
    with h5py.File(path, "w", track_order=True) as h5_file:
        h5_file.attrs["title"] = "Тестовый файл"
        data = h5_file.create_group("data", track_order=True)
        data.attrs["version"] = np.int32(1)
        numeric = data.create_dataset(
            "numeric",
            data=np.arange(60, dtype=np.float64).reshape(3, 4, 5),
            maxshape=(None, 4, 5),
            chunks=(1, 4, 5),
            compression="gzip",
            fletcher32=True,
        )
        numeric.attrs["unit"] = "м/с"
        numeric.attrs["range"] = np.array([0.0, 59.0])
        data.create_dataset("scalar", data=np.float64(3.5))
        data.create_dataset("null", dtype="f8")
        data.create_dataset(
            "empty",
            shape=(0, 3),
            maxshape=(None, 3),
            dtype="i4",
            chunks=(1, 3),
        )
        data.create_dataset("fixed_strings", data=np.array([b"one", b"two"], dtype="S8"))
        data.create_dataset(
            "unicode_strings",
            data=np.array(["один", "два"], dtype=object),
            dtype=h5py.string_dtype("utf-8"),
        )
        data.create_dataset(
            "compound",
            data=np.array([(1, 1.5), (2, 2.5)], dtype=compound_dtype),
        )
        data.create_dataset("state", data=np.array([0, 1], dtype=enum_dtype), dtype=enum_dtype)
        huge = data.create_dataset(
            "huge_logical",
            shape=(1_000_000, 1_000_000),
            dtype="u1",
            chunks=(64, 64),
            fillvalue=7,
        )
        huge.attrs["purpose"] = "Проверка ленивого чтения"

        scale = data.create_dataset("x", data=np.arange(5))
        scale.make_scale("x")
        numeric.dims[2].attach_scale(scale)
        numeric.dims[2].label = "x"

        h5_file["numeric_alias"] = numeric
        h5_file["soft_numeric"] = h5py.SoftLink("/data/numeric")
        h5_file["broken_soft"] = h5py.SoftLink("/missing/object")
        h5_file["external"] = h5py.ExternalLink(external_path.name, "/external_data")
        loops = h5_file.create_group("loops")
        loops["self"] = loops
        h5_file.create_group("данные")

        ref_target = data["scalar"]
        data.attrs["object_ref"] = ref_target.ref
        data.attrs["region_ref"] = numeric.regionref[0:1, 0:2, 0:3]
    return path
