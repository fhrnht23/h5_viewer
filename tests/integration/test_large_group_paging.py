"""Проверка индексной постраничной загрузки больших групп."""

from __future__ import annotations

from pathlib import Path

import h5py

from h5viewer.infrastructure.hdf5.h5py_repository import H5pyRepository


def test_link_pages_are_stable_and_non_overlapping(tmp_path: Path) -> None:
    path = tmp_path / "many-links.h5"
    with h5py.File(path, "w", track_order=True) as h5_file:
        group = h5_file.create_group("ordered", track_order=True)
        for index in range(550):
            group.create_group(f"item-{index:04d}")

    repository = H5pyRepository(path)
    first = repository.list_children("/ordered", 0, 200)
    second = repository.list_children("/ordered", 200, 200)
    last = repository.list_children("/ordered", 400, 200)

    assert first[0].name == "item-0000"
    assert second[0].name == "item-0200"
    assert last[-1].name == "item-0549"
    assert len({link.name for link in first + second + last}) == 550
