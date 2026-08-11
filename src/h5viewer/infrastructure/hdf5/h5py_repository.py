"""Реализация порта HDF5-репозитория с помощью h5py."""

from __future__ import annotations

import json
import math
import os
import shutil
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, cast

import h5py
import numpy as np

from h5viewer.domain.errors import (
    FileOpenError,
    H5ViewerError,
    InsufficientSpaceError,
    ObjectNotFoundError,
    UnsupportedEditError,
    ValidationError,
)
from h5viewer.domain.models import (
    AttributeInfo,
    AttributeSnapshot,
    DatasetCreationOptions,
    DatasetExtent,
    DatasetPage,
    DatasetShrinkSnapshot,
    DatasetSlice,
    DeletedLinkSnapshot,
    DimensionScaleInfo,
    LinkCreationOptions,
    LinkKind,
    LinkRef,
    ObjectDetails,
    ObjectKind,
    ReferenceInfo,
    ReferenceKind,
    ReferenceSourceKind,
    ValidationReport,
    VirtualMappingInfo,
    join_hdf5_path,
    normalize_hdf5_path,
    split_hdf5_path,
)

_VALUE_PREVIEW_ITEMS = 24
_REFERENCE_PREVIEW_ITEMS = 64
_VIRTUAL_MAPPING_PREVIEW_ITEMS = 256
_SNAPSHOT_SPACE_MARGIN = 16 * 1024 * 1024


class H5pyRepository:
    """Доступ к одному физическому HDF5-файлу через короткоживущие handles.

    Объекты h5py не покидают этот класс. Каждый публичный вызов открывает и закрывает
    файл, что явно задаёт владение и исключает устаревшие handles в GUI-моделях.
    """

    def __init__(self, path: Path | str, *, writable: bool = False) -> None:
        self._path = Path(path).expanduser().resolve()
        self._writable = writable
        if not self._path.is_file():
            raise FileOpenError(f"File does not exist: {self._path}")
        try:
            if not h5py.is_hdf5(self._path):
                raise FileOpenError(f"Not an HDF5 file: {self._path}")
        except OSError as exc:
            raise FileOpenError(f"Cannot inspect file: {self._path}") from exc

    @property
    def path(self) -> Path:
        return self._path

    @property
    def writable(self) -> bool:
        return self._writable

    @contextmanager
    def _open(self, *, write: bool = False) -> Iterator[h5py.File]:
        if write and not self._writable:
            raise UnsupportedEditError("Repository is read-only")
        mode = "r+" if write else "r"
        try:
            with h5py.File(self._path, mode) as h5_file:
                yield h5_file
        except H5ViewerError:
            raise
        except (OSError, RuntimeError, ValueError) as exc:
            operation = "write" if write else "read"
            raise FileOpenError(f"HDF5 {operation} failed for {self._path}: {exc}") from exc

    def root(self) -> LinkRef:
        with self._open() as h5_file:
            root = h5_file["/"]
            return LinkRef(
                name="/",
                path="/",
                parent_path="/",
                link_kind=LinkKind.ROOT,
                object_kind=ObjectKind.GROUP,
                object_token=_object_token(root),
                child_count=len(root),
            )

    def link(self, path: str) -> LinkRef:
        """Получить описание ссылки, не обходя соседние объекты группы."""
        normalized = normalize_hdf5_path(path)
        if normalized == "/":
            return self.root()
        parent_path, name = split_hdf5_path(normalized)
        with self._open() as h5_file:
            parent = _require_group(h5_file, parent_path)
            return self._describe_link(parent, name, parent_path)

    def child_count(self, group_path: str) -> int:
        normalized = normalize_hdf5_path(group_path)
        with self._open() as h5_file:
            group = _require_group(h5_file, normalized)
            return len(group)

    def list_children(self, group_path: str, offset: int, limit: int) -> list[LinkRef]:
        if offset < 0 or limit < 0:
            raise ValueError("offset and limit must be non-negative")
        normalized = normalize_hdf5_path(group_path)
        with self._open() as h5_file:
            group = _require_group(h5_file, normalized)
            names = _link_names_page(group, offset, limit)
            return [self._describe_link(group, name, normalized) for name in names]

    def _describe_link(self, group: h5py.Group, name: str, parent_path: str) -> LinkRef:
        path = join_hdf5_path(parent_path, name)
        try:
            link = group.get(name, getlink=True)
        except (KeyError, OSError, RuntimeError, ValueError) as exc:
            return LinkRef(
                name=name,
                path=path,
                parent_path=parent_path,
                link_kind=LinkKind.UNKNOWN,
                object_kind=ObjectKind.BROKEN_LINK,
                error=str(exc),
            )

        link_kind, target_path, external_file = _classify_link(link)
        error: str | None
        try:
            obj = group.get(name)
        except (KeyError, OSError, RuntimeError, ValueError) as exc:
            obj = None
            error = str(exc)
        else:
            error = None

        if obj is None:
            return LinkRef(
                name=name,
                path=path,
                parent_path=parent_path,
                link_kind=link_kind,
                object_kind=ObjectKind.BROKEN_LINK,
                target_path=target_path,
                external_file=external_file,
                error=error or "Link target is unavailable",
            )

        kind = _object_kind(obj)
        shape: tuple[int, ...] | None = None
        dtype: str | None = None
        storage: str | None = None
        child_count: int | None = None
        if isinstance(obj, h5py.Group):
            child_count = len(obj)
        elif isinstance(obj, h5py.Dataset):
            shape = None if obj.shape is None else tuple(int(size) for size in obj.shape)
            dtype = str(obj.dtype)
            storage = _dataset_layout(obj)
        elif isinstance(obj, h5py.Datatype):
            dtype = str(obj.dtype)

        return LinkRef(
            name=name,
            path=path,
            parent_path=parent_path,
            link_kind=link_kind,
            object_kind=kind,
            object_token=_object_token(obj),
            target_path=target_path,
            external_file=external_file,
            shape=shape,
            dtype=dtype,
            storage=storage,
            child_count=child_count,
        )

    def details(self, path: str) -> ObjectDetails:
        normalized = normalize_hdf5_path(path)
        with self._open() as h5_file:
            try:
                obj = h5_file[normalized]
            except KeyError as exc:
                raise ObjectNotFoundError(f"HDF5 object does not exist: {normalized}") from exc

            kind = _object_kind(obj)
            properties: list[tuple[str, str]] = [
                ("path", normalized),
                ("object_kind", kind.value),
                ("object_token", _object_token(obj)),
                ("attribute_count", str(len(obj.attrs))),
            ]
            warnings: list[str] = []

            if normalized == "/":
                properties.extend(
                    [
                        ("file", str(self._path)),
                        ("file_size", str(self._path.stat().st_size)),
                        ("driver", str(h5_file.driver)),
                        ("libver", " → ".join(str(value) for value in h5_file.libver)),
                        ("userblock_size", str(h5_file.userblock_size)),
                        ("hdf5_version", h5py.version.hdf5_version),
                        ("h5py_version", h5py.version.version),
                    ]
                )

            if isinstance(obj, h5py.Group):
                properties.append(("member_count", str(len(obj))))
            elif isinstance(obj, h5py.Dataset):
                properties.extend(_dataset_properties(obj, warnings))
            elif isinstance(obj, h5py.Datatype):
                properties.append(("dtype", str(obj.dtype)))

            attributes = tuple(_attribute_info(obj.attrs, name) for name in obj.attrs)
            references = list(_attribute_references(h5_file, obj, warnings))
            dimension_scales: tuple[DimensionScaleInfo, ...] = ()
            virtual_mappings: tuple[VirtualMappingInfo, ...] = ()
            if isinstance(obj, h5py.Dataset):
                references.extend(_dataset_references(h5_file, obj, warnings))
                dimension_scales = _dimension_scales(obj, warnings)
                virtual_mappings = _virtual_mappings(obj, warnings)
            return ObjectDetails(
                path=normalized,
                kind=kind,
                object_token=_object_token(obj),
                properties=tuple(properties),
                attributes=attributes,
                references=tuple(references),
                dimension_scales=dimension_scales,
                virtual_mappings=virtual_mappings,
                warnings=tuple(warnings),
            )

    def read_dataset_page(self, path: str, selection: DatasetSlice) -> DatasetPage:
        normalized = normalize_hdf5_path(path)
        with self._open() as h5_file:
            dataset = _require_dataset(h5_file, normalized)
            if dataset.shape is None:
                return DatasetPage(
                    values=np.empty((0, 0), dtype=object),
                    row_offset=0,
                    column_offset=0,
                    row_axis_size=0,
                    column_axis_size=0,
                    dtype=str(dataset.dtype),
                    editable=False,
                    warnings=("Null dataspace has no values",),
                )
            shape = tuple(int(size) for size in dataset.shape)
            normalized_selection = _validate_selection(shape, selection)
            editable = _dtype_is_editable(dataset.dtype)
            warnings: list[str] = []
            if not editable:
                warnings.append("This datatype is displayed read-only")

            try:
                values = _read_projection(dataset, normalized_selection)
            except (OSError, RuntimeError, TypeError, ValueError) as exc:
                raise H5ViewerError(f"Cannot read dataset slice {normalized}: {exc}") from exc

            row_size = (
                shape[normalized_selection.row_axis]
                if normalized_selection.row_axis is not None
                else 1
            )
            column_size = (
                shape[normalized_selection.column_axis]
                if normalized_selection.column_axis is not None
                else 1
            )
            return DatasetPage(
                values=values,
                row_offset=normalized_selection.row_offset,
                column_offset=normalized_selection.column_offset,
                row_axis_size=row_size,
                column_axis_size=column_size,
                dtype=str(dataset.dtype),
                editable=editable,
                warnings=tuple(warnings),
            )

    def read_dataset_value(self, path: str, index: tuple[int, ...]) -> Any:
        normalized = normalize_hdf5_path(path)
        with self._open() as h5_file:
            dataset = _require_dataset(h5_file, normalized)
            if dataset.shape is None:
                raise UnsupportedEditError("Null datasets do not contain values")
            checked = _validate_element_index(tuple(int(size) for size in dataset.shape), index)
            if not checked:
                return dataset[()]
            return dataset[checked]

    def write_dataset_value(self, path: str, index: tuple[int, ...], text: str) -> None:
        normalized = normalize_hdf5_path(path)
        with self._open(write=True) as h5_file:
            dataset = _require_dataset(h5_file, normalized)
            if dataset.shape is None:
                raise UnsupportedEditError("Null datasets do not contain values")
            checked = _validate_element_index(tuple(int(size) for size in dataset.shape), index)
            value = _coerce_scalar(text, dataset.dtype)
            if not checked:
                dataset[()] = value
            else:
                dataset[checked] = value
            h5_file.flush()

    def write_dataset_value_raw(self, path: str, index: tuple[int, ...], value: Any) -> None:
        normalized = normalize_hdf5_path(path)
        with self._open(write=True) as h5_file:
            dataset = _require_dataset(h5_file, normalized)
            if dataset.shape is None:
                raise UnsupportedEditError("Null datasets do not contain values")
            checked = _validate_element_index(tuple(int(size) for size in dataset.shape), index)
            if not checked:
                dataset[()] = value
            else:
                dataset[checked] = value
            h5_file.flush()

    def set_attribute(self, path: str, name: str, text: str) -> None:
        normalized = normalize_hdf5_path(path)
        if not name or "/" in name:
            raise UnsupportedEditError("Attribute name must be non-empty and cannot contain '/'")
        with self._open(write=True) as h5_file:
            try:
                obj = h5_file[normalized]
            except KeyError as exc:
                raise ObjectNotFoundError(normalized) from exc
            if name in obj.attrs:
                attribute_id = obj.attrs.get_id(name)
                dtype = attribute_id.dtype
                shape = tuple(int(size) for size in attribute_id.shape)
                value = _coerce_attribute(text, dtype, shape)
                obj.attrs.modify(name, value)
            else:
                obj.attrs.create(name, _parse_json_or_text(text))
            h5_file.flush()

    def read_attribute_value(self, path: str, name: str) -> AttributeSnapshot:
        normalized = normalize_hdf5_path(path)
        with self._open() as h5_file:
            try:
                attributes = h5_file[normalized].attrs
                attribute_id = attributes.get_id(name)
                return AttributeSnapshot(
                    value=attributes[name],
                    dtype=attribute_id.dtype,
                    shape=tuple(int(size) for size in attribute_id.shape),
                )
            except KeyError as exc:
                raise ObjectNotFoundError(f"Attribute does not exist: {normalized}@{name}") from exc

    def write_attribute_value_raw(self, path: str, name: str, snapshot: AttributeSnapshot) -> None:
        normalized = normalize_hdf5_path(path)
        with self._open(write=True) as h5_file:
            try:
                obj = h5_file[normalized]
            except KeyError as exc:
                raise ObjectNotFoundError(normalized) from exc
            if name in obj.attrs:
                obj.attrs.modify(name, snapshot.value)
            else:
                obj.attrs.create(
                    name,
                    snapshot.value,
                    shape=snapshot.shape,
                    dtype=snapshot.dtype,
                )
            h5_file.flush()

    def delete_attribute(self, path: str, name: str) -> None:
        normalized = normalize_hdf5_path(path)
        with self._open(write=True) as h5_file:
            try:
                obj = h5_file[normalized]
                del obj.attrs[name]
            except KeyError as exc:
                raise ObjectNotFoundError(f"Attribute does not exist: {normalized}@{name}") from exc
            h5_file.flush()

    def create_group(self, parent_path: str, name: str) -> str:
        parent_path = normalize_hdf5_path(parent_path)
        _validate_link_name(name)
        destination = join_hdf5_path(parent_path, name)
        with self._open(write=True) as h5_file:
            parent = _require_group(h5_file, parent_path)
            if name in parent:
                raise UnsupportedEditError(f"Link already exists: {destination}")
            parent.create_group(name)
            h5_file.flush()
        return destination

    def create_dataset(self, parent_path: str, name: str, options: DatasetCreationOptions) -> str:
        parent_path = normalize_hdf5_path(parent_path)
        _validate_link_name(name)
        destination = join_hdf5_path(parent_path, name)
        dtype = _creation_dtype(options.dtype)
        keyword_arguments = _dataset_creation_arguments(options, dtype)
        with self._open(write=True) as h5_file:
            parent = _require_group(h5_file, parent_path)
            if parent.get(name, getlink=True) is not None:
                raise UnsupportedEditError(f"Link already exists: {destination}")
            try:
                parent.create_dataset(
                    name,
                    shape=options.shape,
                    dtype=dtype,
                    **keyword_arguments,
                )
            except (OSError, TypeError, ValueError) as exc:
                raise UnsupportedEditError(f"Cannot create dataset: {exc}") from exc
            h5_file.flush()
        return destination

    def dataset_extent(self, path: str) -> DatasetExtent:
        normalized = normalize_hdf5_path(path)
        with self._open() as h5_file:
            dataset = _require_dataset(h5_file, normalized)
            if dataset.shape is None or dataset.maxshape is None:
                raise UnsupportedEditError("Null datasets cannot be resized")
            return DatasetExtent(
                shape=tuple(int(value) for value in dataset.shape),
                maxshape=tuple(None if value is None else int(value) for value in dataset.maxshape),
                chunks=(
                    None
                    if dataset.chunks is None
                    else tuple(int(value) for value in dataset.chunks)
                ),
            )

    def resize_dataset(
        self,
        path: str,
        new_shape: tuple[int, ...],
        *,
        allow_shrink: bool = False,
    ) -> None:
        normalized = normalize_hdf5_path(path)
        target = tuple(int(value) for value in new_shape)
        if any(value < 0 for value in target):
            raise UnsupportedEditError("Dataset dimensions cannot be negative")
        with self._open(write=True) as h5_file:
            dataset = _require_dataset(h5_file, normalized)
            if dataset.shape is None or dataset.maxshape is None:
                raise UnsupportedEditError("Null datasets cannot be resized")
            current = tuple(int(value) for value in dataset.shape)
            maximum = tuple(None if value is None else int(value) for value in dataset.maxshape)
            if len(target) != len(current):
                raise UnsupportedEditError("The new shape must have the same rank")
            if dataset.chunks is None:
                raise UnsupportedEditError("Only chunked datasets can be resized")
            if not allow_shrink and any(
                new < old for old, new in zip(current, target, strict=True)
            ):
                raise UnsupportedEditError(
                    "Shrinking is disabled because it would irreversibly discard data"
                )
            for axis, (value, limit) in enumerate(zip(target, maximum, strict=True)):
                if limit is not None and value > limit:
                    raise UnsupportedEditError(f"Axis {axis} exceeds maxshape: {value} > {limit}")
            try:
                dataset.resize(target)
            except (TypeError, ValueError) as exc:
                raise UnsupportedEditError(f"Cannot resize dataset: {exc}") from exc
            h5_file.flush()

    def shrink_dataset_with_snapshot(
        self,
        path: str,
        new_shape: tuple[int, ...],
    ) -> DatasetShrinkSnapshot:
        """Создать полную копию рабочего файла и выполнить необратимое уменьшение."""
        if not self._writable:
            raise UnsupportedEditError("Repository is read-only")
        normalized = normalize_hdf5_path(path)
        target = tuple(int(value) for value in new_shape)
        extent = self.dataset_extent(normalized)
        if len(target) != len(extent.shape) or not any(
            new < old for old, new in zip(extent.shape, target, strict=True)
        ):
            raise UnsupportedEditError("The new shape does not shrink the dataset")

        required = self._path.stat().st_size + _SNAPSHOT_SPACE_MARGIN
        free = shutil.disk_usage(self._path.parent).free
        if free < required:
            raise InsufficientSpaceError(
                f"Dataset shrinking requires about {required} bytes for undo; "
                f"only {free} bytes are free"
            )

        backup_path = self._path.with_name(
            f".{self._path.name}.{uuid.uuid4().hex}.h5viewer-resize-undo"
        )
        try:
            shutil.copy2(self._path, backup_path)
            _fsync_file(backup_path)
            self.resize_dataset(normalized, target, allow_shrink=True)
        except Exception:
            backup_path.unlink(missing_ok=True)
            raise
        return DatasetShrinkSnapshot(normalized, extent.shape, target, backup_path)

    def restore_dataset_shrink_snapshot(self, snapshot: DatasetShrinkSnapshot) -> None:
        """Проверить снимок и атомарно вернуть его на место рабочей копии."""
        if not self._writable:
            raise UnsupportedEditError("Repository is read-only")
        if not snapshot.backup_path.is_file():
            raise FileOpenError(f"Dataset undo snapshot is missing: {snapshot.backup_path}")
        current = self.dataset_extent(snapshot.dataset_path)
        if current.shape != snapshot.shrunken_shape:
            raise UnsupportedEditError(
                "Cannot restore dataset snapshot because its current shape has changed"
            )
        try:
            with h5py.File(snapshot.backup_path, "r") as backup:
                dataset = _require_dataset(backup, snapshot.dataset_path)
                restored_shape = tuple(int(value) for value in dataset.shape)
                if restored_shape != snapshot.original_shape:
                    raise ValidationError("Dataset undo snapshot has an unexpected shape")
            os.replace(snapshot.backup_path, self._path)
            _fsync_directory(self._path.parent)
        except H5ViewerError:
            raise
        except (OSError, RuntimeError, ValueError) as exc:
            raise FileOpenError(f"Cannot restore dataset undo snapshot: {exc}") from exc

    def create_link(
        self,
        parent_path: str,
        name: str,
        options: LinkCreationOptions,
    ) -> str:
        parent_path = normalize_hdf5_path(parent_path)
        _validate_link_name(name)
        destination = join_hdf5_path(parent_path, name)
        if not options.target_path or "\x00" in options.target_path:
            raise UnsupportedEditError("Link target must not be empty")
        with self._open(write=True) as h5_file:
            parent = _require_group(h5_file, parent_path)
            if parent.get(name, getlink=True) is not None:
                raise UnsupportedEditError(f"Link already exists: {destination}")
            try:
                if options.link_kind is LinkKind.HARD:
                    target = h5_file[normalize_hdf5_path(options.target_path)]
                    parent[name] = target
                elif options.link_kind is LinkKind.SOFT:
                    parent[name] = h5py.SoftLink(options.target_path)
                elif options.link_kind is LinkKind.EXTERNAL:
                    if not options.external_file or "\x00" in options.external_file:
                        raise UnsupportedEditError("External filename must not be empty")
                    parent[name] = h5py.ExternalLink(
                        options.external_file,
                        options.target_path,
                    )
                else:
                    raise UnsupportedEditError(
                        f"Creating {options.link_kind.value} links is not supported"
                    )
            except KeyError as exc:
                raise ObjectNotFoundError(
                    f"Link target does not exist: {options.target_path}"
                ) from exc
            except (OSError, TypeError, ValueError) as exc:
                raise UnsupportedEditError(f"Cannot create link: {exc}") from exc
            h5_file.flush()
        return destination

    def delete_link_with_snapshot(self, path: str) -> DeletedLinkSnapshot:
        normalized = normalize_hdf5_path(path)
        if normalized == "/":
            raise UnsupportedEditError("The root group cannot be deleted")
        parent_path, name = split_hdf5_path(normalized)
        backup_path: Path | None = None
        try:
            with self._open(write=True) as h5_file:
                parent = _require_group(h5_file, parent_path)
                link = parent.get(name, getlink=True)
                if link is None:
                    raise ObjectNotFoundError(normalized)
                if isinstance(link, h5py.SoftLink):
                    snapshot = DeletedLinkSnapshot(LinkKind.SOFT, target_path=str(link.path))
                elif isinstance(link, h5py.ExternalLink):
                    snapshot = DeletedLinkSnapshot(
                        LinkKind.EXTERNAL,
                        target_path=str(link.path),
                        external_file=str(link.filename),
                    )
                elif isinstance(link, h5py.HardLink):
                    target = parent[name]
                    alternate = _find_alternate_hard_link(
                        h5_file,
                        normalized,
                        _object_address(target),
                    )
                    if alternate is not None:
                        snapshot = DeletedLinkSnapshot(
                            LinkKind.HARD,
                            alternate_hard_path=alternate,
                        )
                    else:
                        backup_path = self._path.with_name(
                            f".{self._path.name}.{uuid.uuid4().hex}.h5viewer-undo"
                        )
                        with h5py.File(backup_path, "w") as backup:
                            h5_file.copy(
                                normalized,
                                backup["/"],
                                name="snapshot",
                                expand_soft=False,
                                expand_external=False,
                                expand_refs=False,
                                without_attrs=False,
                            )
                            backup.flush()
                        snapshot = DeletedLinkSnapshot(
                            LinkKind.HARD,
                            backup_path=backup_path,
                        )
                else:
                    raise UnsupportedEditError("Deleting this link type is not supported")
                del parent[name]
                h5_file.flush()
                return snapshot
        except Exception:
            if backup_path is not None:
                backup_path.unlink(missing_ok=True)
            raise

    def restore_deleted_link(self, path: str, snapshot: DeletedLinkSnapshot) -> None:
        normalized = normalize_hdf5_path(path)
        parent_path, name = split_hdf5_path(normalized)
        with self._open(write=True) as h5_file:
            parent = _require_group(h5_file, parent_path)
            if parent.get(name, getlink=True) is not None:
                raise UnsupportedEditError(f"Link already exists: {normalized}")
            if snapshot.link_kind is LinkKind.SOFT and snapshot.target_path is not None:
                parent[name] = h5py.SoftLink(snapshot.target_path)
            elif (
                snapshot.link_kind is LinkKind.EXTERNAL
                and snapshot.target_path is not None
                and snapshot.external_file is not None
            ):
                parent[name] = h5py.ExternalLink(
                    snapshot.external_file,
                    snapshot.target_path,
                )
            elif snapshot.link_kind is LinkKind.HARD:
                if (
                    snapshot.alternate_hard_path is not None
                    and snapshot.alternate_hard_path in h5_file
                ):
                    parent[name] = h5_file[snapshot.alternate_hard_path]
                elif snapshot.backup_path is not None and snapshot.backup_path.is_file():
                    with h5py.File(snapshot.backup_path, "r") as backup:
                        backup.copy(
                            "/snapshot",
                            parent,
                            name=name,
                            expand_soft=False,
                            expand_external=False,
                            expand_refs=False,
                            without_attrs=False,
                        )
                else:
                    raise ObjectNotFoundError("Undo snapshot for the hard link is unavailable")
            else:
                raise UnsupportedEditError("Invalid deleted-link snapshot")
            h5_file.flush()

    def delete_link(self, path: str) -> None:
        normalized = normalize_hdf5_path(path)
        parent_path, name = split_hdf5_path(normalized)
        with self._open(write=True) as h5_file:
            parent = _require_group(h5_file, parent_path)
            if parent.get(name, getlink=True) is None:
                raise ObjectNotFoundError(normalized)
            del parent[name]
            h5_file.flush()

    def move_link(self, source_path: str, destination_path: str) -> None:
        source = normalize_hdf5_path(source_path)
        destination = normalize_hdf5_path(destination_path)
        if source == "/" or destination == "/":
            raise UnsupportedEditError("The root group cannot be moved or replaced")
        destination_parent, destination_name = split_hdf5_path(destination)
        _validate_link_name(destination_name)
        with self._open(write=True) as h5_file:
            _require_group(h5_file, destination_parent)
            if destination in h5_file:
                raise UnsupportedEditError(f"Destination already exists: {destination}")
            try:
                h5_file.move(source, destination)
            except (KeyError, ValueError) as exc:
                raise ObjectNotFoundError(source) from exc
            h5_file.flush()

    def flush(self) -> None:
        if not self._writable:
            return
        with self._open(write=True) as h5_file:
            h5_file.flush()

    def validate(self) -> ValidationReport:
        object_count = 0
        link_count = 0
        warnings: list[str] = []
        try:
            with self._open() as h5_file:
                root = h5_file["/"]
                pending: list[h5py.Group] = [root]
                visited_groups: set[str] = set()
                visited_objects: set[str] = set()
                while pending:
                    group = pending.pop()
                    group_token = _object_token(group)
                    if group_token in visited_groups:
                        continue
                    visited_groups.add(group_token)
                    if group_token not in visited_objects:
                        visited_objects.add(group_token)
                        object_count += 1
                    for name in group:
                        link_count += 1
                        link = group.get(name, getlink=True)
                        if not isinstance(link, h5py.HardLink):
                            try:
                                if group.get(name) is None:
                                    warnings.append(f"Unresolved link: {group.name}/{name}")
                            except (KeyError, OSError, RuntimeError, ValueError):
                                warnings.append(f"Unresolved link: {group.name}/{name}")
                            continue
                        obj = group.get(name)
                        if obj is None:
                            raise ValidationError(f"Hard link has no target: {group.name}/{name}")
                        token = _object_token(obj)
                        if token not in visited_objects:
                            visited_objects.add(token)
                            object_count += 1
                        if isinstance(obj, h5py.Group) and token not in visited_groups:
                            pending.append(obj)
                        elif isinstance(obj, h5py.Dataset):
                            _ = obj.shape, obj.dtype, obj.id.get_storage_size()
        except FileOpenError as exc:
            raise ValidationError(str(exc)) from exc
        return ValidationReport(object_count, link_count, tuple(warnings))


def _require_group(h5_file: h5py.File, path: str) -> h5py.Group:
    try:
        obj = h5_file[path]
    except KeyError as exc:
        raise ObjectNotFoundError(f"Group does not exist: {path}") from exc
    if not isinstance(obj, h5py.Group):
        raise ObjectNotFoundError(f"Object is not a group: {path}")
    return obj


def _require_dataset(h5_file: h5py.File, path: str) -> h5py.Dataset:
    try:
        obj = h5_file[path]
    except KeyError as exc:
        raise ObjectNotFoundError(f"Dataset does not exist: {path}") from exc
    if not isinstance(obj, h5py.Dataset):
        raise ObjectNotFoundError(f"Object is not a dataset: {path}")
    return obj


def _creation_dtype(specification: str) -> np.dtype[Any]:
    """Преобразовать безопасную пользовательскую спецификацию в dtype."""
    normalized = specification.strip().lower().replace("_", "-")
    if normalized in {"utf-8", "utf8", "string", "str"}:
        return cast(np.dtype[Any], np.dtype(h5py.string_dtype(encoding="utf-8")))
    if normalized in {"ascii", "bytes"}:
        return cast(np.dtype[Any], np.dtype(h5py.string_dtype(encoding="ascii")))
    try:
        dtype = np.dtype(specification.strip())
    except TypeError as exc:
        raise UnsupportedEditError(f"Invalid dtype: {specification}") from exc
    if dtype.kind == "U":
        raise UnsupportedEditError("Use 'utf-8' for variable-length Unicode strings")
    if dtype.fields is not None or h5py.check_dtype(ref=dtype) is not None:
        raise UnsupportedEditError("This dtype cannot be created by the basic dialog")
    return dtype


def _dataset_creation_arguments(
    options: DatasetCreationOptions, dtype: np.dtype[Any]
) -> dict[str, Any]:
    """Проверить опции и собрать аргументы для h5py.create_dataset."""
    shape = tuple(int(value) for value in options.shape)
    if any(value < 0 for value in shape):
        raise UnsupportedEditError("Dataset dimensions cannot be negative")
    rank = len(shape)
    if options.maxshape is not None:
        if len(options.maxshape) != rank:
            raise UnsupportedEditError("Shape and maxshape must have the same rank")
        for axis, (size, maximum) in enumerate(zip(shape, options.maxshape, strict=True)):
            if maximum is not None and maximum < size:
                raise UnsupportedEditError(
                    f"maxshape axis {axis} is smaller than the initial shape"
                )
    if options.chunks is not None and (
        len(options.chunks) != rank or any(value <= 0 for value in options.chunks)
    ):
        raise UnsupportedEditError("Chunk shape must contain one positive value per axis")
    compression = options.compression or None
    if compression not in {None, "gzip", "lzf"}:
        raise UnsupportedEditError(f"Unsupported compression filter: {compression}")
    requires_chunks = bool(
        options.maxshape is not None
        or options.chunks is not None
        or compression is not None
        or options.shuffle
        or options.fletcher32
    )
    if options.chunked is False and requires_chunks:
        raise UnsupportedEditError(
            "Contiguous layout cannot use maxshape, chunks, compression or filters"
        )
    if rank == 0 and (requires_chunks or options.chunked is True):
        raise UnsupportedEditError("Scalar datasets cannot be chunked or compressed")

    arguments: dict[str, Any] = {}
    if options.maxshape is not None:
        arguments["maxshape"] = options.maxshape
    if options.chunked is True:
        arguments["chunks"] = options.chunks or True
    elif options.chunks is not None:
        arguments["chunks"] = options.chunks
    if compression is not None:
        arguments["compression"] = compression
        if compression == "gzip" and options.compression_level is not None:
            if not 0 <= options.compression_level <= 9:
                raise UnsupportedEditError("Gzip level must be between 0 and 9")
            arguments["compression_opts"] = options.compression_level
    arguments["shuffle"] = options.shuffle
    arguments["fletcher32"] = options.fletcher32
    if options.fill_value_text is not None:
        arguments["fillvalue"] = _coerce_scalar(options.fill_value_text, dtype)
    return arguments


def _link_names_page(group: h5py.Group, offset: int, limit: int) -> list[str]:
    """Получить страницу имён через HDF5 index без пропуска с начала группы."""
    if limit == 0:
        return []
    names: list[str] = []

    def collect(raw_name: bytes) -> bool:
        names.append(raw_name.decode("utf-8", errors="surrogateescape"))
        return len(names) >= limit

    creation_order = group.id.get_create_plist().get_link_creation_order()
    tracked = bool(creation_order & h5py.h5p.CRT_ORDER_TRACKED)
    index_type = h5py.h5.INDEX_CRT_ORDER if tracked else h5py.h5.INDEX_NAME
    group.id.links.iterate(
        collect,
        idx=offset,
        idx_type=index_type,
        order=h5py.h5.ITER_INC,
    )
    return names


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


def _object_kind(obj: Any) -> ObjectKind:
    if isinstance(obj, h5py.Group):
        return ObjectKind.GROUP
    if isinstance(obj, h5py.Dataset):
        return ObjectKind.DATASET
    if isinstance(obj, h5py.Datatype):
        return ObjectKind.NAMED_DATATYPE
    return ObjectKind.UNKNOWN


def _object_token(obj: h5py.Group | h5py.Dataset | h5py.Datatype) -> str:
    address = _object_address(obj)
    # Номер открытого файла HDF5 меняется между короткими сессиями, поэтому
    # идентичность строится из физического пути и адреса заголовка объекта.
    filename = Path(str(obj.file.filename)).expanduser().resolve()
    return f"{filename}:{address}"


def _object_address(obj: h5py.Group | h5py.Dataset | h5py.Datatype) -> int:
    """Вернуть адрес заголовка объекта внутри физического HDF5-файла."""
    info = h5py.h5o.get_info(obj.id)
    return int(getattr(info, "addr", hash(obj.id)))


def _find_alternate_hard_link(
    h5_file: h5py.File,
    excluded_path: str,
    target_address: int,
) -> str | None:
    """Найти доступный извне alias того же объекта для точного undo."""
    root = h5_file["/"]
    pending: list[tuple[str, h5py.Group]] = [("/", root)]
    visited_groups: set[int] = set()
    while pending:
        group_path, group = pending.pop()
        group_address = _object_address(group)
        if group_address in visited_groups:
            continue
        visited_groups.add(group_address)
        for name in group:
            link = group.get(name, getlink=True)
            if not isinstance(link, h5py.HardLink):
                continue
            candidate_path = join_hdf5_path(group_path, name)
            obj = group.get(name)
            if obj is None:
                continue
            if (
                candidate_path != excluded_path
                and not candidate_path.startswith(f"{excluded_path}/")
                and _object_address(obj) == target_address
            ):
                return candidate_path
            if isinstance(obj, h5py.Group) and _object_address(obj) not in visited_groups:
                pending.append((candidate_path, obj))
    return None


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


def _dataset_properties(dataset: h5py.Dataset, warnings: list[str]) -> list[tuple[str, str]]:
    shape_text = "NULL" if dataset.shape is None else str(tuple(int(v) for v in dataset.shape))
    maxshape = None if dataset.maxshape is None else tuple(dataset.maxshape)
    properties: list[tuple[str, str]] = [
        ("shape", shape_text),
        ("rank", "NULL" if dataset.shape is None else str(dataset.ndim)),
        ("dtype", str(dataset.dtype)),
        ("size", str(dataset.size)),
        ("logical_bytes", str(dataset.nbytes)),
        ("storage_bytes", str(dataset.id.get_storage_size())),
        ("layout", _dataset_layout(dataset)),
        ("chunks", str(dataset.chunks)),
        ("maxshape", str(maxshape)),
        ("compression", str(dataset.compression)),
        ("compression_options", str(dataset.compression_opts)),
        ("shuffle", str(dataset.shuffle)),
        ("fletcher32", str(dataset.fletcher32)),
        ("scaleoffset", str(dataset.scaleoffset)),
        ("fill_value", _display_value(dataset.fillvalue)),
        ("is_virtual", str(dataset.is_virtual)),
        ("is_dimension_scale", str(dataset.is_scale)),
    ]
    external = dataset.external
    if external:
        properties.append(("external_storage", _display_value(external)))
    try:
        filter_ids = tuple(int(value) for value in dataset.filter_ids)
        filter_names = tuple(str(value) for value in dataset.filter_names)
    except AttributeError:
        filter_ids, filter_names = _low_level_filters(dataset)
    properties.append(("filter_ids", str(filter_ids)))
    properties.append(("filter_names", str(filter_names)))
    if dataset.is_virtual:
        try:
            sources = dataset.virtual_sources()
            properties.append(("virtual_source_count", str(len(sources))))
        except (RuntimeError, ValueError) as exc:
            warnings.append(f"Cannot inspect virtual mappings: {exc}")
    try:
        scale_labels = tuple(str(dataset.dims[index].label) for index in range(dataset.ndim))
        properties.append(("dimension_labels", str(scale_labels)))
    except (RuntimeError, TypeError, ValueError) as exc:
        warnings.append(f"Cannot inspect dimension scales: {exc}")
    return properties


def _low_level_filters(dataset: h5py.Dataset) -> tuple[tuple[int, ...], tuple[str, ...]]:
    plist = dataset.id.get_create_plist()
    ids: list[int] = []
    names: list[str] = []
    for index in range(plist.get_nfilters()):
        filter_id, _flags, _values, name = plist.get_filter(index)
        ids.append(int(filter_id))
        names.append(name.decode(errors="replace") if isinstance(name, bytes) else str(name))
    return tuple(ids), tuple(names)


def _attribute_info(attributes: h5py.AttributeManager, name: str) -> AttributeInfo:
    attribute_id = attributes.get_id(name)
    dtype = attribute_id.dtype
    shape = tuple(int(size) for size in attribute_id.shape)
    try:
        value = attributes[name]
        value_text = _display_value(value)
        size = int(np.asarray(value).size)
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        value_text = f"<unavailable: {exc}>"
        size = 0
    return AttributeInfo(
        name=str(name),
        dtype=str(dtype),
        shape=shape,
        value_text=value_text,
        editable=_dtype_is_editable(dtype),
        size=size,
    )


def _attribute_references(
    h5_file: h5py.File,
    obj: h5py.Group | h5py.Dataset | h5py.Datatype,
    warnings: list[str],
) -> tuple[ReferenceInfo, ...]:
    """Извлечь ограниченное число reference из атрибутов объекта."""
    references: list[ReferenceInfo] = []
    for name in obj.attrs:
        try:
            attribute_id = obj.attrs.get_id(name)
            declared_kind = _reference_kind(attribute_id.dtype)
            if declared_kind is None:
                continue
            shape = tuple(int(size) for size in attribute_id.shape)
            value = obj.attrs[name]
            values = np.asarray(value, dtype=object).reshape(-1)
        except (KeyError, OSError, RuntimeError, TypeError, ValueError) as exc:
            warnings.append(f"Cannot inspect references in attribute {name}: {exc}")
            continue
        count = min(int(values.size), _REFERENCE_PREVIEW_ITEMS)
        for flat_index in range(count):
            index = _flat_index(shape, flat_index)
            references.append(
                _describe_reference(
                    h5_file,
                    values[flat_index],
                    source_kind=ReferenceSourceKind.ATTRIBUTE,
                    source_name=str(name),
                    source_index=index,
                    declared_kind=declared_kind,
                )
            )
        if values.size > _REFERENCE_PREVIEW_ITEMS:
            warnings.append(
                f"Attribute {name} reference preview is limited to {_REFERENCE_PREVIEW_ITEMS} items"
            )
    return tuple(references)


def _dataset_references(
    h5_file: h5py.File,
    dataset: h5py.Dataset,
    warnings: list[str],
) -> tuple[ReferenceInfo, ...]:
    """Прочитать не более заданного числа элементов reference-valued dataset."""
    declared_kind = _reference_kind(dataset.dtype)
    if declared_kind is None or dataset.shape is None:
        return ()
    shape = tuple(int(size) for size in dataset.shape)
    total = int(dataset.size)
    references: list[ReferenceInfo] = []
    for flat_index in range(min(total, _REFERENCE_PREVIEW_ITEMS)):
        index = _flat_index(shape, flat_index)
        try:
            value = dataset[()] if not shape else dataset[index]
            reference = _describe_reference(
                h5_file,
                value,
                source_kind=ReferenceSourceKind.DATASET,
                source_name=str(dataset.name or ""),
                source_index=index,
                declared_kind=declared_kind,
            )
        except (KeyError, OSError, RuntimeError, TypeError, ValueError) as exc:
            reference = ReferenceInfo(
                source_kind=ReferenceSourceKind.DATASET,
                source_name=str(dataset.name or ""),
                source_index=index,
                reference_kind=declared_kind,
                error=str(exc),
            )
        references.append(reference)
    if total > _REFERENCE_PREVIEW_ITEMS:
        warnings.append(f"Dataset reference preview is limited to {_REFERENCE_PREVIEW_ITEMS} items")
    return tuple(references)


def _reference_kind(dtype: np.dtype[Any]) -> ReferenceKind | None:
    """Преобразовать reference dtype h5py в доменный тип."""
    reference_class = h5py.check_dtype(ref=dtype)
    if reference_class is h5py.RegionReference:
        return ReferenceKind.REGION
    if reference_class is not None:
        return ReferenceKind.OBJECT
    return None


def _flat_index(shape: tuple[int, ...], flat_index: int) -> tuple[int, ...] | None:
    """Преобразовать плоский индекс в координаты, сохранив scalar как None."""
    if not shape:
        return None
    return tuple(int(value) for value in np.unravel_index(flat_index, shape))


def _describe_reference(
    h5_file: h5py.File,
    value: Any,
    *,
    source_kind: ReferenceSourceKind,
    source_name: str,
    source_index: tuple[int, ...] | None,
    declared_kind: ReferenceKind,
) -> ReferenceInfo:
    """Разрешить одну reference и сразу отделить данные от h5py handle."""
    reference_kind = (
        ReferenceKind.REGION if isinstance(value, h5py.RegionReference) else declared_kind
    )
    try:
        if not value:
            return ReferenceInfo(
                source_kind=source_kind,
                source_name=source_name,
                source_index=source_index,
                reference_kind=reference_kind,
                error="Null reference",
            )
        target = h5_file[value]
    except (KeyError, OSError, RuntimeError, TypeError, ValueError) as exc:
        return ReferenceInfo(
            source_kind=source_kind,
            source_name=source_name,
            source_index=source_index,
            reference_kind=reference_kind,
            error=str(exc),
        )

    target_path = str(target.name) if target.name is not None else None
    selection_type: str | None = None
    selected_points: int | None = None
    bounds: tuple[tuple[int, ...], tuple[int, ...]] | None = None
    error: str | None = None
    if reference_kind is ReferenceKind.REGION:
        try:
            space = h5py.h5r.get_region(value, h5_file.id)
            selection_type, selected_points, bounds = _dataspace_details(space)
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            error = str(exc)
    return ReferenceInfo(
        source_kind=source_kind,
        source_name=source_name,
        source_index=source_index,
        reference_kind=reference_kind,
        target_path=target_path,
        target_kind=_object_kind(target),
        object_token=_object_token(target),
        selection_type=selection_type,
        selected_points=selected_points,
        bounds=bounds,
        error=error,
    )


def _dimension_scales(
    dataset: h5py.Dataset,
    warnings: list[str],
) -> tuple[DimensionScaleInfo, ...]:
    """Собрать labels и пути шкал для каждой оси без чтения их значений."""
    dimensions: list[DimensionScaleInfo] = []
    for axis in range(dataset.ndim):
        try:
            dimension = dataset.dims[axis]
            label = str(dimension.label or "")
            scale_paths = tuple(
                str(scale.name) for scale in dimension.values() if scale.name is not None
            )
        except (KeyError, OSError, RuntimeError, TypeError, ValueError) as exc:
            warnings.append(f"Cannot inspect dimension scale axis {axis}: {exc}")
            label = ""
            scale_paths = ()
        dimensions.append(DimensionScaleInfo(axis, label, scale_paths))
    return tuple(dimensions)


def _virtual_mappings(
    dataset: h5py.Dataset,
    warnings: list[str],
) -> tuple[VirtualMappingInfo, ...]:
    """Преобразовать VDS mappings в ограниченные текстовые сводки."""
    if not dataset.is_virtual:
        return ()
    try:
        sources = dataset.virtual_sources()
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        warnings.append(f"Cannot inspect virtual mappings: {exc}")
        return ()
    mappings = tuple(
        VirtualMappingInfo(
            source_file=_decode_hdf5_text(source.file_name),
            source_dataset=_decode_hdf5_text(source.dset_name),
            virtual_selection=_dataspace_summary(source.vspace),
            source_selection=_dataspace_summary(source.src_space),
        )
        for source in sources[:_VIRTUAL_MAPPING_PREVIEW_ITEMS]
    )
    if len(sources) > _VIRTUAL_MAPPING_PREVIEW_ITEMS:
        warnings.append(
            f"Virtual mapping preview is limited to {_VIRTUAL_MAPPING_PREVIEW_ITEMS} items"
        )
    return mappings


def _decode_hdf5_text(value: str | bytes) -> str:
    """Декодировать имя из низкоуровневого HDF5 API с безопасной заменой."""
    return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else str(value)


def _dataspace_details(
    space: h5py.h5s.SpaceID,
) -> tuple[str, int | None, tuple[tuple[int, ...], tuple[int, ...]] | None]:
    """Вернуть тип, число точек и границы HDF5 dataspace selection."""
    selection_code = int(space.get_select_type())
    selection_type = {
        int(h5py.h5s.SEL_NONE): "none",
        int(h5py.h5s.SEL_POINTS): "points",
        int(h5py.h5s.SEL_HYPERSLABS): "hyperslabs",
        int(h5py.h5s.SEL_ALL): "all",
    }.get(selection_code, f"unknown ({selection_code})")
    selected_points = int(space.get_select_npoints())
    bounds: tuple[tuple[int, ...], tuple[int, ...]] | None = None
    if selected_points > 0:
        start, end = space.get_select_bounds()
        bounds = (
            tuple(int(value) for value in start),
            tuple(int(value) for value in end),
        )
    return selection_type, selected_points, bounds


def _dataspace_summary(space: h5py.h5s.SpaceID) -> str:
    """Создать компактную сводку selection, включая специальный H5S_ALL."""
    try:
        selection_type, selected_points, bounds = _dataspace_details(space)
    except (RuntimeError, ValueError):
        return "all"
    parts = [selection_type]
    if selected_points is not None:
        parts.append(f"points={selected_points}")
    if bounds is not None:
        parts.append(f"bounds={bounds[0]}…{bounds[1]}")
    return "; ".join(parts)


def _display_value(value: Any) -> str:
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, bytes):
        return repr(value)
    if isinstance(value, str):
        return value
    if isinstance(value, np.ndarray):
        return str(
            np.array2string(
                value,
                threshold=_VALUE_PREVIEW_ITEMS,
                edgeitems=3,
            )
        )
    if isinstance(value, (list, tuple)) and len(value) > _VALUE_PREVIEW_ITEMS:
        preview = list(value[:_VALUE_PREVIEW_ITEMS])
        return f"{preview!r} … ({len(value)} items)"
    return repr(value)


def _validate_selection(shape: tuple[int, ...], selection: DatasetSlice) -> DatasetSlice:
    ndim = len(shape)
    if selection.row_count <= 0 or selection.column_count <= 0:
        raise ValueError("Page dimensions must be positive")
    axes = [axis for axis in (selection.row_axis, selection.column_axis) if axis is not None]
    if any(axis < 0 or axis >= ndim for axis in axes):
        raise ValueError("Displayed axis is outside the dataset rank")
    if len(set(axes)) != len(axes):
        raise ValueError("Row and column axes must be different")
    if ndim == 0 and axes:
        raise ValueError("Scalar datasets do not have display axes")
    if ndim > 0 and selection.row_axis is None:
        raise ValueError("A non-scalar dataset requires a row axis")
    fixed = selection.fixed_indices
    if len(fixed) != ndim:
        fixed = (0,) * ndim
    for axis, index in enumerate(fixed):
        if axis in axes:
            continue
        if index < 0 or index >= shape[axis]:
            raise ValueError(f"Fixed index {index} is outside axis {axis}")
    row_size = shape[selection.row_axis] if selection.row_axis is not None else 1
    column_size = shape[selection.column_axis] if selection.column_axis is not None else 1
    row_offset = min(max(0, selection.row_offset), max(0, row_size - 1))
    column_offset = min(max(0, selection.column_offset), max(0, column_size - 1))
    return DatasetSlice(
        row_axis=selection.row_axis,
        column_axis=selection.column_axis,
        fixed_indices=fixed,
        row_offset=row_offset,
        column_offset=column_offset,
        row_count=selection.row_count,
        column_count=selection.column_count,
    )


def _read_projection(dataset: h5py.Dataset, selection: DatasetSlice) -> np.ndarray[Any, Any]:
    if dataset.ndim == 0:
        return np.asarray(dataset[()]).reshape(1, 1)
    selectors: list[int | slice] = []
    for axis, size in enumerate(dataset.shape):
        if axis == selection.row_axis:
            stop = min(int(size), selection.row_offset + selection.row_count)
            selectors.append(slice(selection.row_offset, stop))
        elif axis == selection.column_axis:
            stop = min(int(size), selection.column_offset + selection.column_count)
            selectors.append(slice(selection.column_offset, stop))
        else:
            selectors.append(selection.fixed_indices[axis])
    values = np.asarray(dataset[tuple(selectors)])
    if selection.column_axis is None:
        return values.reshape(values.shape[0], 1)
    if cast(int, selection.row_axis) > selection.column_axis:
        values = values.T
    return values.reshape(values.shape[0], values.shape[1])


def _validate_element_index(shape: tuple[int, ...], index: tuple[int, ...]) -> tuple[int, ...]:
    if len(index) != len(shape):
        raise UnsupportedEditError("Dataset index rank does not match dataset rank")
    for axis, (value, size) in enumerate(zip(index, shape, strict=True)):
        if value < 0 or value >= size:
            raise UnsupportedEditError(f"Index {value} is outside axis {axis}")
    return index


def _dtype_is_editable(dtype: np.dtype[Any]) -> bool:
    if dtype.fields is not None:
        return False
    if h5py.check_dtype(ref=dtype) is not None:
        return False
    vlen = h5py.check_dtype(vlen=dtype)
    if vlen is not None and vlen not in {str, bytes}:
        return False
    return dtype.kind in {"b", "i", "u", "f", "c", "S", "U", "O"}


def _coerce_scalar(text: str, dtype: np.dtype[Any]) -> Any:
    if not _dtype_is_editable(dtype):
        raise UnsupportedEditError(f"Editing dtype {dtype} is not supported safely")
    enum_values = h5py.check_dtype(enum=dtype)
    if enum_values and text in enum_values:
        return enum_values[text]
    string_info = h5py.check_string_dtype(dtype)
    if string_info is not None:
        value: str | bytes
        if dtype.kind == "S" or string_info.encoding == "ascii":
            try:
                parsed = _parse_json_or_text(text)
                value = (
                    parsed
                    if isinstance(parsed, bytes)
                    else str(parsed).encode(string_info.encoding)
                )
            except UnicodeEncodeError as exc:
                raise UnsupportedEditError(str(exc)) from exc
            if string_info.length is not None and len(value) > string_info.length:
                raise UnsupportedEditError(
                    f"Encoded value is {len(value)} bytes; fixed string allows {string_info.length}"
                )
            return value
        parsed = _parse_json_or_text(text)
        value = parsed.decode() if isinstance(parsed, bytes) else str(parsed)
        if (
            string_info.length is not None
            and len(value.encode(string_info.encoding)) > string_info.length
        ):
            raise UnsupportedEditError("Value does not fit the fixed-length string datatype")
        return value
    if dtype.kind == "b":
        lowered = text.strip().lower()
        if lowered in {"true", "1", "yes", "on"}:
            return True
        if lowered in {"false", "0", "no", "off"}:
            return False
        raise UnsupportedEditError("Boolean value must be true/false or 1/0")
    try:
        array = np.asarray(_parse_json_or_text(text), dtype=dtype)
    except (TypeError, ValueError, OverflowError) as exc:
        raise UnsupportedEditError(f"Value is not valid for dtype {dtype}: {exc}") from exc
    if array.size != 1:
        raise UnsupportedEditError("A dataset cell requires exactly one scalar value")
    return array.reshape(()).item()


def _coerce_attribute(text: str, dtype: np.dtype[Any], shape: tuple[int, ...]) -> Any:
    if shape == ():
        return _coerce_scalar(text, dtype)
    if not _dtype_is_editable(dtype):
        raise UnsupportedEditError(f"Editing attribute dtype {dtype} is not supported safely")
    parsed = _parse_json_or_text(text)
    try:
        result = np.asarray(parsed, dtype=dtype)
    except (TypeError, ValueError, OverflowError) as exc:
        raise UnsupportedEditError(f"Attribute value is invalid for dtype {dtype}: {exc}") from exc
    if result.shape != shape:
        raise UnsupportedEditError(f"Attribute shape must remain {shape}, got {result.shape}")
    return result


def _parse_json_or_text(text: str) -> Any:
    stripped = text.strip()
    if not stripped:
        return ""
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError:
        return text
    if isinstance(value, float) and not math.isfinite(value):
        raise UnsupportedEditError("Non-finite JSON numbers must be entered as a typed scalar")
    return value


def _validate_link_name(name: str) -> None:
    if not name or "/" in name or "\x00" in name:
        raise UnsupportedEditError("Link name must be non-empty and cannot contain '/' or NUL")


def _fsync_file(path: Path) -> None:
    """Гарантировать запись готового снимка на носитель перед изменением файла."""
    with path.open("rb") as handle:
        os.fsync(handle.fileno())


def _fsync_directory(path: Path) -> None:
    """Синхронизировать атомарную замену каталога там, где это поддерживается."""
    if os.name == "nt":
        return
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        # Некоторые файловые системы не поддерживают fsync для каталогов.
        return
    finally:
        os.close(descriptor)
