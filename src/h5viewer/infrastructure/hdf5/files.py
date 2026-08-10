"""Файловые операции создания и предварительной проверки HDF5."""

from __future__ import annotations

from pathlib import Path

import h5py

from h5viewer.domain.errors import FileOpenError


def create_empty_hdf5(path: Path | str) -> Path:
    """Создать новый пустой HDF5-файл, не перезаписывая существующий."""
    destination = Path(path).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise FileOpenError(f"Файл уже существует: {destination}")
    try:
        with h5py.File(destination, "x") as h5_file:
            h5_file.flush()
    except (OSError, RuntimeError, ValueError) as exc:
        raise FileOpenError(f"Не удалось создать HDF5-файл: {exc}") from exc
    return destination
