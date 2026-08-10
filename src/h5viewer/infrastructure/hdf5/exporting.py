"""Атомарный порционный экспорт HDF5 dataset в CSV и NumPy NPY."""

from __future__ import annotations

import csv
import itertools
import os
import shutil
import tempfile
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import h5py
import numpy as np

from h5viewer.domain.errors import (
    ExportError,
    InsufficientSpaceError,
    ObjectNotFoundError,
)
from h5viewer.domain.models import (
    DatasetExportOptions,
    DatasetExportReport,
    DatasetSlice,
    ExportFormat,
    default_dataset_slice,
    normalize_hdf5_path,
)

ExportProgress = Callable[[int, int], None]
CancelCallback = Callable[[], bool]


def export_hdf5_dataset(
    source_path: Path | str,
    dataset_path: str,
    destination: Path | str,
    options: DatasetExportOptions,
    *,
    progress: ExportProgress | None = None,
    cancelled: CancelCallback | None = None,
) -> DatasetExportReport:
    """Экспортировать dataset во временный файл и атомарно опубликовать результат."""
    source = Path(source_path).expanduser().resolve()
    target = Path(destination).expanduser().resolve()
    normalized = normalize_hdf5_path(dataset_path)
    _validate_export_paths(source, target)
    if options.block_bytes <= 0 or options.csv_row_bytes_limit <= 0:
        raise ExportError("Export memory limits must be positive")

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=target.parent,
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    exported = 0
    total = 0
    was_cancelled = False
    try:
        with h5py.File(source, "r") as h5_file:
            try:
                dataset = h5_file[normalized]
            except KeyError as exc:
                raise ObjectNotFoundError(normalized) from exc
            if not isinstance(dataset, h5py.Dataset):
                raise ExportError(f"HDF5 path is not a dataset: {normalized}")
            if dataset.shape is None:
                raise ExportError("Null dataset does not contain exportable values")
            if options.export_format is ExportFormat.NPY:
                total = int(dataset.size)
                _check_npy_support(dataset, target)
                exported, was_cancelled = _export_npy(
                    dataset,
                    temporary,
                    options.block_bytes,
                    progress,
                    cancelled,
                )
            elif options.export_format is ExportFormat.CSV:
                selection = options.selection or default_dataset_slice(
                    tuple(int(size) for size in dataset.shape)
                )
                exported, total, was_cancelled = _export_csv(
                    dataset,
                    temporary,
                    selection,
                    options,
                    progress,
                    cancelled,
                )
            else:
                raise ExportError(f"Unsupported export format: {options.export_format}")
        if was_cancelled:
            temporary.unlink(missing_ok=True)
            return DatasetExportReport(target, exported, total, 0, cancelled=True)
        os.replace(temporary, target)
        written_bytes = target.stat().st_size
        return DatasetExportReport(target, exported, total, written_bytes)
    except (ExportError, InsufficientSpaceError, ObjectNotFoundError):
        temporary.unlink(missing_ok=True)
        raise
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        temporary.unlink(missing_ok=True)
        raise ExportError(f"Dataset export failed: {exc}") from exc
    finally:
        temporary.unlink(missing_ok=True)


def _validate_export_paths(source: Path, destination: Path) -> None:
    """Не позволить экспорту заменить исходный HDF5-файл."""
    if not source.is_file():
        raise ExportError(f"Source file does not exist: {source}")
    if source == destination:
        raise ExportError("Export destination cannot replace the source HDF5 file")
    if not destination.parent.is_dir():
        raise ExportError(f"Export directory does not exist: {destination.parent}")


def _check_npy_support(dataset: h5py.Dataset, destination: Path) -> None:
    """Проверить dtype и свободное место до создания полного NPY."""
    if dataset.dtype.hasobject or h5py.check_dtype(ref=dataset.dtype) is not None:
        raise ExportError("NPY export does not support object, vlen or reference dtype")
    required = int(dataset.nbytes) + 4096
    free = int(shutil.disk_usage(destination.parent).free)
    if required > free:
        raise InsufficientSpaceError(
            f"NPY export requires about {required} bytes, but only {free} bytes are free"
        )


def _export_npy(
    dataset: h5py.Dataset,
    destination: Path,
    block_bytes: int,
    progress: ExportProgress | None,
    cancelled: CancelCallback | None,
) -> tuple[int, bool]:
    """Записать полный dataset через memory map, не материализуя его целиком."""
    assert dataset.shape is not None
    shape = tuple(int(size) for size in dataset.shape)
    memory_map = np.lib.format.open_memmap(  # type: ignore[no-untyped-call]
        destination,
        mode="w+",
        dtype=dataset.dtype,
        shape=shape,
    )
    exported = 0
    was_cancelled = False
    try:
        for selection in _block_slices(shape, dataset.dtype, block_bytes):
            if cancelled is not None and cancelled():
                was_cancelled = True
                break
            if selection:
                values = dataset[selection]
                memory_map[selection] = values
                exported += int(np.asarray(values).size)
            else:
                value = dataset[()]
                memory_map[()] = value
                exported = 1
            memory_map.flush()
            if progress is not None:
                progress(exported, int(dataset.size))
    finally:
        memory_map.flush()
        del memory_map
    return exported, was_cancelled


def _export_csv(
    dataset: h5py.Dataset,
    destination: Path,
    selection: DatasetSlice,
    options: DatasetExportOptions,
    progress: ExportProgress | None,
    cancelled: CancelCallback | None,
) -> tuple[int, int, bool]:
    """Записать полную выбранную 2-D projection строковыми блоками."""
    assert dataset.shape is not None
    shape = tuple(int(size) for size in dataset.shape)
    checked = _validate_csv_selection(shape, selection)
    row_count = shape[checked.row_axis] if checked.row_axis is not None else 1
    column_count = shape[checked.column_axis] if checked.column_axis is not None else 1
    total = row_count * column_count
    row_bytes = column_count * max(1, int(dataset.dtype.itemsize))
    if row_bytes > options.csv_row_bytes_limit:
        raise ExportError(
            f"One CSV row requires about {row_bytes} bytes; limit is "
            f"{options.csv_row_bytes_limit} bytes"
        )
    block_rows = max(1, min(row_count, options.block_bytes // max(1, row_bytes)))
    exported = 0
    was_cancelled = False
    with destination.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        if not shape:
            writer.writerow([_csv_value(dataset[()], dataset.file)])
            exported = 1
            if progress is not None:
                progress(1, 1)
            return exported, total, False
        for start in range(0, row_count, block_rows):
            if cancelled is not None and cancelled():
                was_cancelled = True
                break
            stop = min(row_count, start + block_rows)
            values = _read_csv_rows(dataset, checked, start, stop, column_count)
            for row in values:
                writer.writerow(_csv_value(value, dataset.file) for value in row)
            exported += int(values.size)
            if progress is not None:
                progress(exported, total)
    return exported, total, was_cancelled


def _validate_csv_selection(
    shape: tuple[int, ...],
    selection: DatasetSlice,
) -> DatasetSlice:
    """Проверить оси projection; offsets страницы для полного CSV не применяются."""
    rank = len(shape)
    if rank == 0:
        return DatasetSlice(None, None, ())
    if selection.row_axis is None or not 0 <= selection.row_axis < rank:
        raise ExportError("CSV projection requires a valid row axis")
    if selection.column_axis is not None and not 0 <= selection.column_axis < rank:
        raise ExportError("CSV projection column axis is outside dataset rank")
    if selection.column_axis == selection.row_axis:
        raise ExportError("CSV projection axes must be different")
    fixed = selection.fixed_indices
    if len(fixed) != rank:
        raise ExportError("CSV fixed index count must match dataset rank")
    displayed = {selection.row_axis, selection.column_axis}
    for axis, index in enumerate(fixed):
        if axis in displayed:
            continue
        if index < 0 or index >= shape[axis]:
            raise ExportError(f"CSV fixed index {index} is outside axis {axis}")
    return DatasetSlice(
        selection.row_axis,
        selection.column_axis,
        fixed,
        row_offset=0,
        column_offset=0,
    )


def _read_csv_rows(
    dataset: h5py.Dataset,
    selection: DatasetSlice,
    start: int,
    stop: int,
    column_count: int,
) -> np.ndarray[Any, Any]:
    """Прочитать блок projection в ориентации строки × столбцы."""
    assert dataset.shape is not None and selection.row_axis is not None
    selectors: list[int | slice] = list(selection.fixed_indices)
    selectors[selection.row_axis] = slice(start, stop)
    if selection.column_axis is not None:
        selectors[selection.column_axis] = slice(0, column_count)
    values = np.asarray(dataset[tuple(selectors)])
    if selection.column_axis is None:
        return values.reshape(stop - start, 1)
    if selection.row_axis > selection.column_axis:
        values = values.T
    return values.reshape(stop - start, column_count)


def _csv_value(value: Any, h5_file: h5py.File) -> Any:
    """Преобразовать scalar, bytes, sequence или reference в одну CSV-ячейку."""
    if isinstance(value, (h5py.Reference, h5py.RegionReference)):
        try:
            if not value:
                return "NULL"
            target = h5_file[value]
            if isinstance(value, h5py.RegionReference):
                space = h5py.h5r.get_region(value, h5_file.id)
                return (
                    f"{target.name}; selection={int(space.get_select_type())}; "
                    f"points={int(space.get_select_npoints())}"
                )
            return str(target.name)
        except (KeyError, OSError, RuntimeError, TypeError, ValueError) as exc:
            return f"<unavailable reference: {exc}>"
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, np.ndarray):
        return repr(value.tolist())
    if isinstance(value, (tuple, list, dict)):
        return repr(value)
    return value


def _block_slices(
    shape: tuple[int, ...],
    dtype: np.dtype[Any],
    block_bytes: int,
) -> Iterator[tuple[slice, ...]]:
    """Разбить N-D dataset на блоки в пределах заданного бюджета памяти."""
    if not shape:
        yield ()
        return
    if any(size == 0 for size in shape):
        return
    max_elements = max(1, block_bytes // max(1, int(dtype.itemsize)))
    block_shape = [1] * len(shape)
    remaining = max_elements
    for axis in range(len(shape) - 1, -1, -1):
        block_shape[axis] = min(shape[axis], max(1, remaining))
        remaining = max(1, remaining // block_shape[axis])
    starts = [range(0, size, block) for size, block in zip(shape, block_shape, strict=True)]
    for origin in itertools.product(*starts):
        yield tuple(
            slice(start, min(size, start + block))
            for start, size, block in zip(origin, shape, block_shape, strict=True)
        )
