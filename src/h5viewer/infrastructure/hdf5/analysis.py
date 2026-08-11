"""Ограниченный поиск метаданных и порционное сравнение HDF5-файлов."""

from __future__ import annotations

import hashlib
import itertools
import math
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import h5py
import numpy as np

from h5viewer.domain.errors import FileOpenError
from h5viewer.domain.models import (
    ComparisonOptions,
    DifferenceKind,
    FileComparisonReport,
    FileDifference,
    GroupSizeReport,
    LinkKind,
    MetadataField,
    MetadataMatch,
    MetadataSearchOptions,
    MetadataSearchReport,
    ObjectKind,
    join_hdf5_path,
    normalize_hdf5_path,
)

ProgressCallback = Callable[[int, str], None]
CancelCallback = Callable[[], bool]

_ATTRIBUTE_VALUE_LIMIT = 1024 * 1024
_ATTRIBUTE_ELEMENT_LIMIT = 10_000
_SEARCH_PREVIEW_ITEMS = 32
_SEARCH_PREVIEW_CHARACTERS = 240
_OBJECT_BLOCK_ELEMENT_LIMIT = 65_536


@dataclass(frozen=True, slots=True)
class _LiveEntry:
    """Ссылка и доступный через неё объект во время одного открытого handle."""

    path: str
    link_kind: LinkKind
    target_path: str | None
    external_file: str | None
    obj: Any | None


@dataclass(frozen=True, slots=True)
class _AttributeFingerprint:
    """Сравнимый отпечаток небольшого атрибута."""

    dtype: str
    shape: tuple[int, ...]
    digest: str | None
    preview: str


@dataclass(frozen=True, slots=True)
class _EntrySnapshot:
    """Не содержащая h5py handle сводка одной именованной ссылки."""

    object_kind: ObjectKind
    link_kind: LinkKind
    target_path: str | None
    external_file: str | None
    metadata: tuple[tuple[str, str], ...]
    attributes: tuple[tuple[str, _AttributeFingerprint], ...]
    compare_data: bool


def calculate_group_size(
    path: Path | str,
    group_path: str,
    *,
    progress: ProgressCallback | None = None,
    cancelled: CancelCallback | None = None,
) -> GroupSizeReport:
    """Суммировать уникальные datasets группы без чтения их содержимого."""
    source_path = Path(path).expanduser().resolve()
    normalized = normalize_hdf5_path(group_path)
    logical_bytes = 0
    storage_bytes = 0
    dataset_count = 0
    group_count = 0
    scanned_links = 0
    duplicate_objects = 0
    external_links_skipped = 0
    unresolved_links = 0
    virtual_dataset_count = 0
    was_cancelled = False
    try:
        with h5py.File(source_path, "r") as h5_file:
            try:
                root = h5_file[normalized]
            except KeyError as exc:
                raise ValueError(f"Group does not exist: {normalized}") from exc
            if not isinstance(root, h5py.Group):
                raise ValueError(f"Object is not a group: {normalized}")
            pending: list[tuple[str, h5py.Group]] = [(normalized, root)]
            visited_groups: set[int] = set()
            visited_datasets: set[int] = set()
            while pending:
                if cancelled is not None and cancelled():
                    was_cancelled = True
                    break
                current_path, group = pending.pop()
                group_address = _object_address(group)
                if group_address in visited_groups:
                    duplicate_objects += 1
                    continue
                visited_groups.add(group_address)
                group_count += 1
                for name in group:
                    if cancelled is not None and cancelled():
                        was_cancelled = True
                        break
                    scanned_links += 1
                    entry_path = join_hdf5_path(current_path, name)
                    if progress is not None and (scanned_links == 1 or scanned_links % 50 == 0):
                        progress(scanned_links, entry_path)
                    try:
                        link = group.get(name, getlink=True)
                    except (KeyError, OSError, RuntimeError, ValueError):
                        unresolved_links += 1
                        continue
                    if isinstance(link, h5py.ExternalLink):
                        external_links_skipped += 1
                        continue
                    try:
                        obj = group.get(name)
                    except (KeyError, OSError, RuntimeError, ValueError):
                        unresolved_links += 1
                        continue
                    if obj is None:
                        unresolved_links += 1
                        continue
                    if isinstance(obj, h5py.Group):
                        address = _object_address(obj)
                        if address in visited_groups:
                            duplicate_objects += 1
                        else:
                            pending.append((entry_path, obj))
                        continue
                    if not isinstance(obj, h5py.Dataset):
                        continue
                    address = _object_address(obj)
                    if address in visited_datasets:
                        duplicate_objects += 1
                        continue
                    visited_datasets.add(address)
                    dataset_count += 1
                    logical_bytes += int(obj.nbytes)
                    try:
                        storage_bytes += int(obj.id.get_storage_size())
                    except (OSError, RuntimeError, ValueError):
                        unresolved_links += 1
                    if obj.is_virtual:
                        virtual_dataset_count += 1
                if was_cancelled:
                    break
    except (OSError, RuntimeError) as exc:
        raise FileOpenError(f"HDF5 size analysis failed for {source_path}: {exc}") from exc
    return GroupSizeReport(
        path=normalized,
        logical_bytes=logical_bytes,
        storage_bytes=storage_bytes,
        dataset_count=dataset_count,
        group_count=group_count,
        scanned_links=scanned_links,
        duplicate_objects=duplicate_objects,
        external_links_skipped=external_links_skipped,
        unresolved_links=unresolved_links,
        virtual_dataset_count=virtual_dataset_count,
        cancelled=was_cancelled,
    )


def search_hdf5_metadata(
    path: Path | str,
    options: MetadataSearchOptions,
    *,
    progress: ProgressCallback | None = None,
    cancelled: CancelCallback | None = None,
) -> MetadataSearchReport:
    """Найти запрос в путях, типах, dataset metadata и небольших атрибутах."""
    query = options.query.strip()
    if not query:
        raise ValueError("Search query must not be empty")
    if options.max_results <= 0:
        raise ValueError("Maximum result count must be positive")
    source_path = Path(path).expanduser().resolve()
    matches: list[MetadataMatch] = []
    warnings: list[str] = []
    scanned = 0
    was_cancelled = False
    truncated = False

    def contains(value: str) -> bool:
        if options.case_sensitive:
            return query in value
        return query.casefold() in value.casefold()

    def add_match(
        entry: _LiveEntry,
        field: MetadataField,
        name: str,
        value: str,
    ) -> bool:
        nonlocal truncated
        if not contains(value):
            return True
        if len(matches) >= options.max_results:
            truncated = True
            return False
        matches.append(
            MetadataMatch(
                path=entry.path,
                object_kind=_object_kind(entry.obj),
                field=field,
                name=name,
                value_preview=_shorten(value),
            )
        )
        return True

    try:
        with h5py.File(source_path, "r") as h5_file:
            for entry in _walk_entries(h5_file, warnings, cancelled):
                if cancelled is not None and cancelled():
                    was_cancelled = True
                    break
                scanned += 1
                if progress is not None and (scanned == 1 or scanned % 100 == 0):
                    progress(scanned, entry.path)
                if not add_match(entry, MetadataField.PATH, "path", entry.path):
                    break
                object_kind = _object_kind(entry.obj)
                if not add_match(
                    entry,
                    MetadataField.OBJECT_KIND,
                    "object_kind",
                    object_kind.value,
                ):
                    break
                if not add_match(
                    entry,
                    MetadataField.LINK_KIND,
                    "link_kind",
                    entry.link_kind.value,
                ):
                    break
                if isinstance(entry.obj, h5py.Dataset):
                    for name, value in _dataset_search_metadata(entry.obj):
                        if not add_match(
                            entry,
                            MetadataField.DATASET_METADATA,
                            name,
                            value,
                        ):
                            break
                    if truncated:
                        break
                if entry.obj is None:
                    continue
                for name in entry.obj.attrs:
                    if not add_match(
                        entry,
                        MetadataField.ATTRIBUTE_NAME,
                        str(name),
                        str(name),
                    ):
                        break
                    if not options.include_attribute_values:
                        continue
                    value_text = _searchable_attribute_value(
                        entry.obj.attrs,
                        str(name),
                        entry.path,
                        warnings,
                    )
                    if value_text is not None and not add_match(
                        entry,
                        MetadataField.ATTRIBUTE_VALUE,
                        str(name),
                        value_text,
                    ):
                        break
                if truncated:
                    break
            if cancelled is not None and cancelled():
                was_cancelled = True
    except (OSError, RuntimeError, ValueError) as exc:
        raise FileOpenError(f"Cannot search HDF5 file {source_path}: {exc}") from exc

    return MetadataSearchReport(
        matches=tuple(matches),
        scanned_links=scanned,
        truncated=truncated,
        cancelled=was_cancelled,
        warnings=_unique(warnings),
    )


def compare_hdf5_files(
    left_path: Path | str,
    right_path: Path | str,
    options: ComparisonOptions,
    *,
    progress: ProgressCallback | None = None,
    cancelled: CancelCallback | None = None,
) -> FileComparisonReport:
    """Сравнить структуру и данные, читая dataset блоками ограниченного размера."""
    _validate_comparison_options(options)
    left = Path(left_path).expanduser().resolve()
    right = Path(right_path).expanduser().resolve()
    warnings: list[str] = []
    differences: list[FileDifference] = []
    compared_objects = 0
    compared_datasets = 0
    compared_elements = 0
    was_cancelled = False
    truncated = False

    try:
        left_manifest, left_cancelled = _collect_manifest(
            left,
            warnings,
            progress,
            cancelled,
            progress_offset=0,
        )
        right_manifest, right_cancelled = _collect_manifest(
            right,
            warnings,
            progress,
            cancelled,
            progress_offset=len(left_manifest),
        )
    except (OSError, RuntimeError, ValueError) as exc:
        raise FileOpenError(f"Cannot compare HDF5 files: {exc}") from exc

    if left_cancelled or right_cancelled:
        return FileComparisonReport(
            differences=(),
            compared_objects=0,
            compared_datasets=0,
            compared_elements=0,
            cancelled=True,
            warnings=_unique(warnings),
        )

    def add_difference(difference: FileDifference) -> bool:
        nonlocal truncated
        if len(differences) >= options.max_differences:
            truncated = True
            return False
        differences.append(difference)
        return True

    left_paths = set(left_manifest)
    right_paths = set(right_manifest)
    for path in sorted(left_paths - right_paths):
        if not add_difference(FileDifference(path, DifferenceKind.ONLY_LEFT, "Path")):
            break
    if not truncated:
        for path in sorted(right_paths - left_paths):
            if not add_difference(FileDifference(path, DifferenceKind.ONLY_RIGHT, "Path")):
                break

    common_paths = sorted(left_paths & right_paths)
    data_paths: list[str] = []
    if not truncated:
        for path in common_paths:
            if cancelled is not None and cancelled():
                was_cancelled = True
                break
            compared_objects += 1
            left_entry = left_manifest[path]
            right_entry = right_manifest[path]
            for difference in _compare_entry(path, left_entry, right_entry):
                if not add_difference(difference):
                    break
            if truncated:
                break
            if (
                options.compare_data
                and left_entry.object_kind is ObjectKind.DATASET
                and right_entry.object_kind is ObjectKind.DATASET
                and left_entry.compare_data
                and right_entry.compare_data
                and dict(left_entry.metadata).get("shape")
                == dict(right_entry.metadata).get("shape")
                and dict(left_entry.metadata).get("dtype")
                == dict(right_entry.metadata).get("dtype")
            ):
                data_paths.append(path)

    if options.compare_data and not truncated and not was_cancelled:
        try:
            with h5py.File(left, "r") as left_file, h5py.File(right, "r") as right_file:
                for path in data_paths:
                    if cancelled is not None and cancelled():
                        was_cancelled = True
                        break
                    left_dataset = left_file[path]
                    right_dataset = right_file[path]
                    if not isinstance(left_dataset, h5py.Dataset) or not isinstance(
                        right_dataset, h5py.Dataset
                    ):
                        continue
                    compared_datasets += 1
                    dataset_difference, element_count, warning = _compare_dataset_data(
                        path,
                        left_dataset,
                        right_dataset,
                        options,
                        cancelled,
                        progress,
                    )
                    compared_elements += element_count
                    if cancelled is not None and cancelled():
                        was_cancelled = True
                        break
                    if warning is not None:
                        warnings.append(warning)
                    if dataset_difference is not None and not add_difference(dataset_difference):
                        break
        except (OSError, RuntimeError, ValueError) as exc:
            raise FileOpenError(f"Cannot compare HDF5 dataset data: {exc}") from exc

    return FileComparisonReport(
        differences=tuple(differences),
        compared_objects=compared_objects,
        compared_datasets=compared_datasets,
        compared_elements=compared_elements,
        truncated=truncated,
        cancelled=was_cancelled,
        warnings=_unique(warnings),
    )


def _walk_entries(
    h5_file: h5py.File,
    warnings: list[str],
    cancelled: CancelCallback | None,
) -> Iterator[_LiveEntry]:
    """Обойти именованные ссылки без повторного раскрытия group aliases и циклов."""
    root = h5_file["/"]
    yield _LiveEntry("/", LinkKind.ROOT, None, None, root)
    pending: list[tuple[str, h5py.Group]] = [("/", root)]
    expanded_groups: set[int] = set()
    while pending:
        if cancelled is not None and cancelled():
            return
        group_path, group = pending.pop()
        address = _object_address(group)
        if address in expanded_groups:
            continue
        expanded_groups.add(address)
        try:
            names = tuple(str(name) for name in group)
        except (OSError, RuntimeError, ValueError) as exc:
            warnings.append(f"Cannot enumerate group {group_path}: {exc}")
            continue
        for name in reversed(names):
            path = join_hdf5_path(group_path, name)
            try:
                raw_link = group.get(name, getlink=True)
                link_kind, target_path, external_file = _classify_link(raw_link)
                obj = group.get(name)
            except (KeyError, OSError, RuntimeError, ValueError) as exc:
                warnings.append(f"Cannot resolve link {path}: {exc}")
                obj = None
                link_kind, target_path, external_file = LinkKind.UNKNOWN, None, None
            entry = _LiveEntry(path, link_kind, target_path, external_file, obj)
            yield entry
            if isinstance(obj, h5py.Group) and link_kind is LinkKind.HARD:
                pending.append((path, obj))


def _collect_manifest(
    path: Path,
    warnings: list[str],
    progress: ProgressCallback | None,
    cancelled: CancelCallback | None,
    *,
    progress_offset: int,
) -> tuple[dict[str, _EntrySnapshot], bool]:
    """Собрать сравнимый manifest без сохранения открытых объектов h5py."""
    manifest: dict[str, _EntrySnapshot] = {}
    seen_datasets: set[int] = set()
    with h5py.File(path, "r") as h5_file:
        for count, entry in enumerate(_walk_entries(h5_file, warnings, cancelled), start=1):
            if cancelled is not None and cancelled():
                return manifest, True
            compare_data = False
            if isinstance(entry.obj, h5py.Dataset) and entry.link_kind in {
                LinkKind.ROOT,
                LinkKind.HARD,
            }:
                address = _object_address(entry.obj)
                compare_data = address not in seen_datasets
                seen_datasets.add(address)
            manifest[entry.path] = _snapshot_entry(
                entry,
                warnings,
                compare_data=compare_data,
            )
            if progress is not None and (count == 1 or count % 100 == 0):
                progress(progress_offset + count, entry.path)
    return manifest, bool(cancelled is not None and cancelled())


def _snapshot_entry(
    entry: _LiveEntry,
    warnings: list[str],
    *,
    compare_data: bool,
) -> _EntrySnapshot:
    """Отделить metadata и attribute fingerprints от живого объекта."""
    obj = entry.obj
    kind = _object_kind(obj)
    metadata: list[tuple[str, str]] = []
    attributes: list[tuple[str, _AttributeFingerprint]] = []
    if isinstance(obj, h5py.Dataset):
        metadata.extend(_dataset_comparison_metadata(obj, warnings))
    elif isinstance(obj, h5py.Group):
        metadata.append(("member_count", str(len(obj))))
    elif isinstance(obj, h5py.Datatype):
        metadata.append(("dtype", str(obj.dtype)))
    if obj is not None:
        for name in obj.attrs:
            attributes.append(
                (
                    str(name),
                    _attribute_fingerprint(obj.attrs, str(name), entry.path, warnings),
                )
            )
    return _EntrySnapshot(
        object_kind=kind,
        link_kind=entry.link_kind,
        target_path=entry.target_path,
        external_file=entry.external_file,
        metadata=tuple(metadata),
        attributes=tuple(attributes),
        compare_data=compare_data,
    )


def _compare_entry(
    path: str,
    left: _EntrySnapshot,
    right: _EntrySnapshot,
) -> tuple[FileDifference, ...]:
    """Сравнить link, тип объекта, metadata и атрибуты одного пути."""
    differences: list[FileDifference] = []
    if (
        left.link_kind,
        left.target_path,
        left.external_file,
    ) != (
        right.link_kind,
        right.target_path,
        right.external_file,
    ):
        differences.append(
            FileDifference(
                path,
                DifferenceKind.LINK,
                "Link",
                _link_summary(left),
                _link_summary(right),
            )
        )
    if left.object_kind is not right.object_kind:
        differences.append(
            FileDifference(
                path,
                DifferenceKind.OBJECT_KIND,
                "Object kind",
                left.object_kind.value,
                right.object_kind.value,
            )
        )
        return tuple(differences)

    left_metadata = dict(left.metadata)
    right_metadata = dict(right.metadata)
    for name in sorted(set(left_metadata) | set(right_metadata)):
        left_value = left_metadata.get(name, "")
        right_value = right_metadata.get(name, "")
        if left_value != right_value:
            differences.append(
                FileDifference(
                    path,
                    DifferenceKind.METADATA,
                    name,
                    left_value,
                    right_value,
                )
            )

    left_attributes = dict(left.attributes)
    right_attributes = dict(right.attributes)
    for name in sorted(set(left_attributes) | set(right_attributes)):
        left_attribute = left_attributes.get(name)
        right_attribute = right_attributes.get(name)
        if left_attribute is None or right_attribute is None:
            differences.append(
                FileDifference(
                    path,
                    DifferenceKind.ATTRIBUTE,
                    name,
                    left_attribute.preview if left_attribute is not None else "",
                    right_attribute.preview if right_attribute is not None else "",
                )
            )
            continue
        if (
            left_attribute.dtype != right_attribute.dtype
            or left_attribute.shape != right_attribute.shape
            or (
                left_attribute.digest is not None
                and right_attribute.digest is not None
                and left_attribute.digest != right_attribute.digest
            )
        ):
            differences.append(
                FileDifference(
                    path,
                    DifferenceKind.ATTRIBUTE,
                    name,
                    left_attribute.preview,
                    right_attribute.preview,
                )
            )
    return tuple(differences)


def _compare_dataset_data(
    path: str,
    left: h5py.Dataset,
    right: h5py.Dataset,
    options: ComparisonOptions,
    cancelled: CancelCallback | None,
    progress: ProgressCallback | None,
) -> tuple[FileDifference | None, int, str | None]:
    """Найти первое data-различие dataset, сохраняя ограничение памяти."""
    if left.shape is None or right.shape is None:
        return None, 0, None
    shape = tuple(int(size) for size in left.shape)
    compared = 0
    reference_dtype = h5py.check_dtype(ref=left.dtype) is not None
    for selection in _comparison_slices(left, right, shape, options.block_bytes):
        if cancelled is not None and cancelled():
            return None, compared, None
        try:
            left_values = np.asarray(left[()] if not selection else left[selection])
            right_values = np.asarray(right[()] if not selection else right[selection])
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            return (
                FileDifference(path, DifferenceKind.ERROR, "Dataset read", str(exc), str(exc)),
                compared,
                None,
            )
        if reference_dtype:
            left_values = _reference_descriptors(left.file, left_values)
            right_values = _reference_descriptors(right.file, right_values)
        compared += int(left_values.size)
        if progress is not None:
            progress(compared, path)
        local_index = _first_mismatch(
            left_values,
            right_values,
            relative_tolerance=options.relative_tolerance,
            absolute_tolerance=options.absolute_tolerance,
        )
        if local_index is None:
            continue
        global_index = _global_index(selection, local_index)
        left_value = left_values[local_index] if left_values.ndim else left_values[()]
        right_value = right_values[local_index] if right_values.ndim else right_values[()]
        return (
            FileDifference(
                path,
                DifferenceKind.DATA,
                f"Index {global_index}",
                _shorten(_scalar_text(left_value)),
                _shorten(_scalar_text(right_value)),
            ),
            compared,
            None,
        )
    return None, compared, None


def _comparison_slices(
    left: h5py.Dataset,
    right: h5py.Dataset,
    shape: tuple[int, ...],
    block_bytes: int,
) -> Iterator[tuple[slice, ...]]:
    """Для chunked dataset читать только объединение физически выделенных chunks."""
    if (
        left.chunks is None
        or right.chunks is None
        or left.is_virtual
        or right.is_virtual
        or left.chunks != right.chunks
    ):
        yield from _block_slices(shape, left.dtype, block_bytes)
        return
    left_offsets = _allocated_chunk_offsets(left)
    right_offsets = _allocated_chunk_offsets(right)
    if left_offsets is None or right_offsets is None:
        yield from _block_slices(shape, left.dtype, block_bytes)
        return
    chunks = tuple(int(size) for size in left.chunks)
    for offset in sorted(left_offsets | right_offsets):
        region_shape = tuple(
            min(chunk, size - start)
            for start, size, chunk in zip(offset, shape, chunks, strict=True)
        )
        for local in _block_slices(region_shape, left.dtype, block_bytes):
            yield tuple(
                slice(start + int(axis.start or 0), start + int(axis.stop or 0))
                for start, axis in zip(offset, local, strict=True)
            )


def _allocated_chunk_offsets(dataset: h5py.Dataset) -> set[tuple[int, ...]] | None:
    """Получить координаты выделенных chunks или сообщить об отсутствии API."""
    try:
        count = int(dataset.id.get_num_chunks())
        return {
            tuple(int(value) for value in dataset.id.get_chunk_info(index).chunk_offset)
            for index in range(count)
        }
    except (AttributeError, OSError, RuntimeError, ValueError):
        return None


def _reference_descriptors(
    h5_file: h5py.File,
    values: np.ndarray[Any, Any],
) -> np.ndarray[Any, Any]:
    """Преобразовать references двух файлов в сравнимые описания целей."""
    result = np.empty(values.shape, dtype=object)
    indices: Iterator[tuple[int, ...]]
    indices = iter([()]) if values.ndim == 0 else np.ndindex(values.shape)
    for index in indices:
        value = values[()] if not index else values[index]
        result[index] = _reference_descriptor(h5_file, value)
    return result


def _reference_descriptor(h5_file: h5py.File, value: Any) -> tuple[Any, ...]:
    """Описать null, object или region reference без файловой identity."""
    try:
        if not value:
            return ("null",)
        target = h5_file[value]
        target_path = str(target.name)
        if not isinstance(value, h5py.RegionReference):
            return ("object", target_path, _object_kind(target).value)
        space = h5py.h5r.get_region(value, h5_file.id)
        points = int(space.get_select_npoints())
        bounds = space.get_select_bounds() if points > 0 else None
        return ("region", target_path, int(space.get_select_type()), points, bounds)
    except (KeyError, OSError, RuntimeError, TypeError, ValueError) as exc:
        return ("error", str(exc))


def _first_mismatch(
    left: np.ndarray[Any, Any],
    right: np.ndarray[Any, Any],
    *,
    relative_tolerance: float,
    absolute_tolerance: float,
) -> tuple[int, ...] | None:
    """Вернуть локальный индекс первого отличия двух одинаковых блоков."""
    if left.shape != right.shape:
        return ()
    if left.dtype.kind in {"f", "c"} and right.dtype.kind in {"f", "c"}:
        equal = np.isclose(
            left,
            right,
            rtol=relative_tolerance,
            atol=absolute_tolerance,
            equal_nan=True,
        )
        flat = np.flatnonzero(~equal.reshape(-1))
        if flat.size == 0:
            return None
        return tuple(int(value) for value in np.unravel_index(int(flat[0]), left.shape))
    if np.array_equal(left, right):
        return None
    if left.ndim == 0:
        return ()
    for index in np.ndindex(left.shape):
        if not _scalar_equal(left[index], right[index]):
            return tuple(int(value) for value in index)
    return None


def _scalar_equal(left: Any, right: Any) -> bool:
    """Безопасно сравнить scalar, compound field или vlen sequence."""
    if isinstance(left, np.ndarray) or isinstance(right, np.ndarray):
        return bool(np.array_equal(np.asarray(left), np.asarray(right), equal_nan=True))
    try:
        result = left == right
    except (TypeError, ValueError):
        return _scalar_text(left) == _scalar_text(right)
    if isinstance(result, np.ndarray):
        return bool(np.all(result))
    return bool(result)


def _block_slices(
    shape: tuple[int, ...],
    dtype: np.dtype[Any],
    block_bytes: int,
) -> Iterator[tuple[slice, ...]]:
    """Разбить N-D shape на прямоугольные блоки не больше заданного бюджета."""
    if not shape:
        yield ()
        return
    if any(size == 0 for size in shape):
        return
    item_size = max(1, int(dtype.itemsize))
    max_elements = max(1, block_bytes // item_size)
    if dtype.hasobject:
        max_elements = min(max_elements, _OBJECT_BLOCK_ELEMENT_LIMIT)
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


def _global_index(selection: tuple[slice, ...], local: tuple[int, ...]) -> tuple[int, ...]:
    """Перевести индекс внутри блока в индекс исходного dataset."""
    if not selection:
        return ()
    return tuple(
        int((axis.start or 0) + offset) for axis, offset in zip(selection, local, strict=True)
    )


def _dataset_search_metadata(dataset: h5py.Dataset) -> tuple[tuple[str, str], ...]:
    """Вернуть поля dataset, полезные для текстового поиска."""
    return (
        ("dtype", str(dataset.dtype)),
        ("shape", "NULL" if dataset.shape is None else str(tuple(dataset.shape))),
        ("layout", _dataset_layout(dataset)),
        ("compression", str(dataset.compression)),
    )


def _dataset_comparison_metadata(
    dataset: h5py.Dataset,
    warnings: list[str],
) -> tuple[tuple[str, str], ...]:
    """Собрать семантически значимые свойства dataset для сравнения."""
    metadata: list[tuple[str, str]] = [
        ("shape", "NULL" if dataset.shape is None else str(tuple(dataset.shape))),
        ("dtype", str(dataset.dtype)),
        ("maxshape", str(dataset.maxshape)),
        ("layout", _dataset_layout(dataset)),
        ("chunks", str(dataset.chunks)),
        ("compression", str(dataset.compression)),
        ("compression_options", str(dataset.compression_opts)),
        ("shuffle", str(dataset.shuffle)),
        ("fletcher32", str(dataset.fletcher32)),
        ("scaleoffset", str(dataset.scaleoffset)),
        ("fill_value", _scalar_text(dataset.fillvalue)),
        ("external_storage", _shorten(repr(dataset.external))),
        ("is_virtual", str(dataset.is_virtual)),
        ("is_dimension_scale", str(dataset.is_scale)),
    ]
    try:
        labels = tuple(str(dataset.dims[axis].label or "") for axis in range(dataset.ndim))
        scales = tuple(
            tuple(str(scale.name) for scale in dataset.dims[axis].values())
            for axis in range(dataset.ndim)
        )
        metadata.extend((("dimension_labels", str(labels)), ("dimension_scales", str(scales))))
    except (KeyError, OSError, RuntimeError, TypeError, ValueError) as exc:
        warnings.append(f"Cannot compare dimension scales for {dataset.name}: {exc}")
    if dataset.is_virtual:
        try:
            mappings = tuple(
                (
                    _decode_text(source.file_name),
                    _decode_text(source.dset_name),
                    _dataspace_summary(source.vspace),
                    _dataspace_summary(source.src_space),
                )
                for source in dataset.virtual_sources()
            )
            metadata.append(("virtual_mappings", _shorten(repr(mappings), limit=2000)))
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            warnings.append(f"Cannot compare virtual mappings for {dataset.name}: {exc}")
    return tuple(metadata)


def _searchable_attribute_value(
    attributes: h5py.AttributeManager,
    name: str,
    path: str,
    warnings: list[str],
) -> str | None:
    """Прочитать небольшой атрибут либо явно пропустить потенциально большой."""
    attribute_id = attributes.get_id(name)
    shape = tuple(int(size) for size in attribute_id.shape)
    if not _attribute_is_bounded(attribute_id, shape):
        warnings.append(f"Attribute value search skipped for {path}@{name}")
        return None
    try:
        return _value_text(attributes[name])
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        warnings.append(f"Cannot read attribute {path}@{name}: {exc}")
        return None


def _attribute_fingerprint(
    attributes: h5py.AttributeManager,
    name: str,
    path: str,
    warnings: list[str],
) -> _AttributeFingerprint:
    """Вычислить стабильный digest небольшого атрибута без хранения значения."""
    attribute_id = attributes.get_id(name)
    dtype = attribute_id.dtype
    shape = tuple(int(size) for size in attribute_id.shape)
    if not _attribute_is_bounded(attribute_id, shape):
        warnings.append(f"Attribute value comparison skipped for {path}@{name}")
        return _AttributeFingerprint(str(dtype), shape, None, "<value skipped>")
    try:
        value = attributes[name]
        preview = _value_text(value)
        digest = _value_digest(value, dtype)
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        warnings.append(f"Cannot compare attribute {path}@{name}: {exc}")
        return _AttributeFingerprint(str(dtype), shape, None, f"<unavailable: {exc}>")
    if digest is None:
        warnings.append(f"Reference attribute value comparison skipped for {path}@{name}")
    return _AttributeFingerprint(str(dtype), shape, digest, preview)


def _attribute_is_bounded(attribute_id: Any, shape: tuple[int, ...]) -> bool:
    """Проверить лимит storage и числа элементов до чтения значения."""
    count = math.prod(shape) if shape else 1
    try:
        storage_size = int(attribute_id.get_storage_size())
    except (AttributeError, RuntimeError, ValueError):
        storage_size = count * max(1, int(attribute_id.dtype.itemsize))
    return count <= _ATTRIBUTE_ELEMENT_LIMIT and storage_size <= _ATTRIBUTE_VALUE_LIMIT


def _value_digest(value: Any, dtype: np.dtype[Any]) -> str | None:
    """Создать стабильный SHA-256 для обычных и строковых значений."""
    if h5py.check_dtype(ref=dtype) is not None:
        return None
    values = np.asarray(value)
    digest = hashlib.sha256()
    digest.update(str(dtype).encode("utf-8"))
    digest.update(repr(values.shape).encode("ascii"))
    if values.dtype.hasobject:
        for item in values.reshape(-1):
            digest.update(_stable_item_bytes(item))
            digest.update(b"\0")
    else:
        digest.update(values.tobytes(order="C"))
    return digest.hexdigest()


def _stable_item_bytes(value: Any) -> bytes:
    """Сериализовать один vlen/string элемент без адресов Python-объектов."""
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, bytes):
        return b"b:" + value
    if isinstance(value, str):
        return b"s:" + value.encode("utf-8", errors="surrogatepass")
    if isinstance(value, np.ndarray):
        return repr(value.tolist()).encode("utf-8", errors="backslashreplace")
    return repr(value).encode("utf-8", errors="backslashreplace")


def _value_text(value: Any) -> str:
    """Создать короткое представление значения для поиска и отчёта."""
    if isinstance(value, np.ndarray):
        text = np.array2string(value, threshold=_SEARCH_PREVIEW_ITEMS, edgeitems=3)
    else:
        text = _scalar_text(value)
    return _shorten(text)


def _scalar_text(value: Any) -> str:
    """Преобразовать NumPy scalar или HDF5-значение в читаемый текст."""
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, bytes):
        return repr(value)
    if isinstance(value, str):
        return value
    return repr(value)


def _shorten(value: str, *, limit: int = _SEARCH_PREVIEW_CHARACTERS) -> str:
    """Ограничить размер одной ячейки результата."""
    return value if len(value) <= limit else f"{value[: limit - 1]}…"


def _object_kind(obj: Any | None) -> ObjectKind:
    if obj is None:
        return ObjectKind.BROKEN_LINK
    if isinstance(obj, h5py.Group):
        return ObjectKind.GROUP
    if isinstance(obj, h5py.Dataset):
        return ObjectKind.DATASET
    if isinstance(obj, h5py.Datatype):
        return ObjectKind.NAMED_DATATYPE
    return ObjectKind.UNKNOWN


def _object_address(obj: h5py.Group | h5py.Dataset) -> int:
    """Вернуть адрес заголовка объекта для обнаружения aliases и циклов."""
    info = h5py.h5o.get_info(obj.id)
    return int(getattr(info, "addr", hash(obj.id)))


def _classify_link(link: Any) -> tuple[LinkKind, str | None, str | None]:
    if isinstance(link, h5py.HardLink):
        return LinkKind.HARD, None, None
    if isinstance(link, h5py.SoftLink):
        return LinkKind.SOFT, str(link.path), None
    if isinstance(link, h5py.ExternalLink):
        return LinkKind.EXTERNAL, str(link.path), str(link.filename)
    if link is None:
        return LinkKind.UNKNOWN, None, None
    return LinkKind.USER_DEFINED, None, None


def _dataset_layout(dataset: h5py.Dataset) -> str:
    try:
        layout = dataset.id.get_create_plist().get_layout()
    except (RuntimeError, ValueError):
        return "unknown"
    return {
        h5py.h5d.COMPACT: "compact",
        h5py.h5d.CONTIGUOUS: "contiguous",
        h5py.h5d.CHUNKED: "chunked",
        h5py.h5d.VIRTUAL: "virtual",
    }.get(layout, f"unknown ({layout})")


def _link_summary(entry: _EntrySnapshot) -> str:
    """Собрать краткое описание именованной ссылки."""
    parts = [entry.link_kind.value]
    if entry.external_file:
        parts.append(entry.external_file)
    if entry.target_path:
        parts.append(entry.target_path)
    return ":".join(parts)


def _decode_text(value: str | bytes) -> str:
    return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else str(value)


def _dataspace_summary(space: h5py.h5s.SpaceID) -> str:
    """Описать VDS selection, включая специальное значение H5S_ALL."""
    try:
        selection_type = int(space.get_select_type())
        points = int(space.get_select_npoints())
        bounds = space.get_select_bounds() if points > 0 else None
    except (RuntimeError, ValueError):
        return "all"
    return f"type={selection_type}; points={points}; bounds={bounds}"


def _validate_comparison_options(options: ComparisonOptions) -> None:
    """Отклонить лимиты, нарушающие гарантию ограниченного чтения."""
    if options.max_differences <= 0:
        raise ValueError("Maximum difference count must be positive")
    if options.block_bytes <= 0:
        raise ValueError("Block size must be positive")
    if options.relative_tolerance < 0 or options.absolute_tolerance < 0:
        raise ValueError("Comparison tolerances must be non-negative")


def _unique(values: list[str]) -> tuple[str, ...]:
    """Сохранить порядок предупреждений и убрать точные повторы."""
    return tuple(dict.fromkeys(values))
