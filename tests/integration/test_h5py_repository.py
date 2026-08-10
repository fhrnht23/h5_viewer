"""Интеграционные тесты h5py-репозитория."""

from __future__ import annotations

import shutil
from pathlib import Path

import h5py
import numpy as np
import pytest

from h5viewer.domain.errors import UnsupportedEditError
from h5viewer.domain.models import (
    DatasetCreationOptions,
    DatasetSlice,
    LinkCreationOptions,
    LinkKind,
    ObjectKind,
    default_dataset_slice,
)
from h5viewer.infrastructure.hdf5.h5py_repository import H5pyRepository
from h5viewer.infrastructure.hdf5.validation import validate_hdf5_in_subprocess


def test_lists_links_without_following_cycles_forever(sample_hdf5: Path) -> None:
    repository = H5pyRepository(sample_hdf5)
    root = repository.root()
    links = repository.list_children("/", 0, repository.child_count("/"))
    by_name = {link.name: link for link in links}

    assert root.object_kind is ObjectKind.GROUP
    assert by_name["soft_numeric"].link_kind is LinkKind.SOFT
    assert by_name["external"].link_kind is LinkKind.EXTERNAL
    assert by_name["broken_soft"].object_kind is ObjectKind.BROKEN_LINK
    data_links = {link.name: link for link in repository.list_children("/data", 0, 20)}
    assert by_name["numeric_alias"].object_token == data_links["numeric"].object_token

    loop = repository.list_children("/loops", 0, 10)[0]
    assert loop.object_kind is ObjectKind.GROUP
    assert loop.object_token == by_name["loops"].object_token


def test_details_include_storage_and_attributes(sample_hdf5: Path) -> None:
    details = H5pyRepository(sample_hdf5).details("/data/numeric")
    properties = dict(details.properties)
    attributes = {attribute.name: attribute for attribute in details.attributes}

    assert properties["shape"] == "(3, 4, 5)"
    assert properties["layout"] == "chunked"
    assert properties["compression"] == "gzip"
    assert attributes["unit"].value_text == "м/с"


def test_reads_only_requested_projection(sample_hdf5: Path) -> None:
    repository = H5pyRepository(sample_hdf5)
    page = repository.read_dataset_page(
        "/data/numeric",
        DatasetSlice(
            row_axis=1,
            column_axis=2,
            fixed_indices=(2, 0, 0),
            row_offset=1,
            column_offset=2,
            row_count=2,
            column_count=2,
        ),
    )
    np.testing.assert_array_equal(page.values, np.array([[47.0, 48.0], [52.0, 53.0]]))

    huge = repository.read_dataset_page(
        "/data/huge_logical", default_dataset_slice((1_000_000, 1_000_000))
    )
    assert huge.values.shape == (100, 50)
    assert np.all(huge.values == 7)


def test_writes_supported_values_and_attributes(sample_hdf5: Path, tmp_path: Path) -> None:
    writable_path = tmp_path / "writable.h5"
    shutil.copy2(sample_hdf5, writable_path)
    repository = H5pyRepository(writable_path, writable=True)

    repository.write_dataset_value("/data/numeric", (1, 2, 3), "123.25")
    repository.set_attribute("/data/numeric", "unit", "км/ч")

    assert repository.read_dataset_value("/data/numeric", (1, 2, 3)) == 123.25
    assert repository.read_attribute_value("/data/numeric", "unit").value == "км/ч"


def test_creates_and_safely_expands_dataset(sample_hdf5: Path, tmp_path: Path) -> None:
    writable_path = tmp_path / "dataset-operations.h5"
    shutil.copy2(sample_hdf5, writable_path)
    repository = H5pyRepository(writable_path, writable=True)
    options = DatasetCreationOptions(
        shape=(2, 3),
        dtype="float32",
        maxshape=(None, 3),
        chunked=True,
        chunks=(2, 3),
        compression="gzip",
        compression_level=4,
        fill_value_text="1.5",
        shuffle=True,
    )

    repository.create_dataset("/data", "created", options)
    extent = repository.dataset_extent("/data/created")
    assert extent.shape == (2, 3)
    assert extent.maxshape == (None, 3)
    assert extent.chunks == (2, 3)
    assert repository.read_dataset_value("/data/created", (1, 2)) == pytest.approx(1.5)

    repository.resize_dataset("/data/created", (5, 3))
    assert repository.dataset_extent("/data/created").shape == (5, 3)
    with pytest.raises(UnsupportedEditError, match="Shrinking"):
        repository.resize_dataset("/data/created", (1, 3))


def test_creates_hard_soft_and_external_links(sample_hdf5: Path, tmp_path: Path) -> None:
    writable_path = tmp_path / "link-operations.h5"
    shutil.copy2(sample_hdf5, writable_path)
    repository = H5pyRepository(writable_path, writable=True)

    repository.create_link(
        "/data",
        "hard_created",
        LinkCreationOptions(LinkKind.HARD, "/data/numeric"),
    )
    repository.create_link(
        "/data",
        "soft_created",
        LinkCreationOptions(LinkKind.SOFT, "/missing/allowed"),
    )
    repository.create_link(
        "/data",
        "external_created",
        LinkCreationOptions(LinkKind.EXTERNAL, "/external_data", "external.h5"),
    )

    with h5py.File(writable_path, "r") as h5_file:
        hard = h5_file["/data"].get("hard_created", getlink=True)
        soft = h5_file["/data"].get("soft_created", getlink=True)
        external = h5_file["/data"].get("external_created", getlink=True)
        assert isinstance(hard, h5py.HardLink)
        assert h5_file["/data/hard_created"].id == h5_file["/data/numeric"].id
        assert isinstance(soft, h5py.SoftLink)
        assert soft.path == "/missing/allowed"
        assert isinstance(external, h5py.ExternalLink)
        assert external.filename == "external.h5"


def test_validation_terminates_on_hard_link_cycle(sample_hdf5: Path) -> None:
    report = H5pyRepository(sample_hdf5).validate()
    assert report.object_count > 5
    assert report.link_count > report.object_count
    assert any("broken_soft" in warning for warning in report.warnings)


def test_validation_can_run_in_isolated_process(sample_hdf5: Path) -> None:
    report = validate_hdf5_in_subprocess(sample_hdf5, timeout_seconds=20)
    assert report.object_count > 5
    assert report.link_count > report.object_count
