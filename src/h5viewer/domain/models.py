"""Не зависящие от UI-фреймворка типы значений HDF5."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt


class ObjectKind(str, Enum):
    """Логический тип объекта HDF5 или неразрешённой ссылки."""

    FILE = "file"
    GROUP = "group"
    DATASET = "dataset"
    NAMED_DATATYPE = "named_datatype"
    BROKEN_LINK = "broken_link"
    UNKNOWN = "unknown"


class LinkKind(str, Enum):
    """Тип ссылки, принадлежащей группе HDF5."""

    ROOT = "root"
    HARD = "hard"
    SOFT = "soft"
    EXTERNAL = "external"
    USER_DEFINED = "user_defined"
    UNKNOWN = "unknown"


class ReferenceKind(str, Enum):
    """Тип значения HDF5 reference."""

    OBJECT = "object"
    REGION = "region"


class ReferenceSourceKind(str, Enum):
    """Место, из которого прочитано значение HDF5 reference."""

    ATTRIBUTE = "attribute"
    DATASET = "dataset"


@dataclass(frozen=True, slots=True)
class LinkCreationOptions:
    """Параметры новой hard, soft или external link."""

    link_kind: LinkKind
    target_path: str
    external_file: str | None = None


@dataclass(frozen=True, slots=True)
class DeletedLinkSnapshot:
    """Достаточные сведения для точного восстановления удалённой ссылки."""

    link_kind: LinkKind
    target_path: str | None = None
    external_file: str | None = None
    alternate_hard_path: str | None = None
    backup_path: Path | None = None


@dataclass(frozen=True, slots=True)
class FileFingerprint:
    """Недорогой отпечаток для обнаружения внешних изменений файла."""

    size: int
    modified_ns: int
    inode: int | None = None

    @classmethod
    def from_path(cls, path: Path) -> FileFingerprint:
        stat = path.stat()
        return cls(
            size=stat.st_size,
            modified_ns=stat.st_mtime_ns,
            inode=getattr(stat, "st_ino", None),
        )


@dataclass(frozen=True, slots=True)
class LinkRef:
    """Именованное ребро графа HDF5."""

    name: str
    path: str
    parent_path: str
    link_kind: LinkKind
    object_kind: ObjectKind
    object_token: str | None = None
    target_path: str | None = None
    external_file: str | None = None
    shape: tuple[int, ...] | None = None
    dtype: str | None = None
    storage: str | None = None
    child_count: int | None = None
    error: str | None = None

    @property
    def can_expand(self) -> bool:
        """Проверить, можно ли раскрыть ссылку без разрешения другого файла."""
        return self.object_kind is ObjectKind.GROUP and self.link_kind in {
            LinkKind.ROOT,
            LinkKind.HARD,
        }


@dataclass(frozen=True, slots=True)
class ObjectRef:
    """Ссылка на объект внутри одного физического документа HDF5."""

    document_id: str
    path: str
    kind: ObjectKind
    object_token: str | None = None


@dataclass(frozen=True, slots=True)
class AttributeInfo:
    """Безопасные для отображения метаданные одного атрибута HDF5."""

    name: str
    dtype: str
    shape: tuple[int, ...]
    value_text: str
    editable: bool
    size: int


@dataclass(frozen=True, slots=True)
class AttributeSnapshot:
    """Полное значение и тип атрибута для точной операции undo."""

    value: Any
    dtype: np.dtype[Any]
    shape: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class ReferenceInfo:
    """Ограниченная сводка object или region reference без h5py handle."""

    source_kind: ReferenceSourceKind
    source_name: str
    reference_kind: ReferenceKind
    source_index: tuple[int, ...] | None = None
    target_path: str | None = None
    target_kind: ObjectKind | None = None
    object_token: str | None = None
    selection_type: str | None = None
    selected_points: int | None = None
    bounds: tuple[tuple[int, ...], tuple[int, ...]] | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class DimensionScaleInfo:
    """Метка одной оси dataset и прикреплённые к ней шкалы."""

    axis: int
    label: str
    scale_paths: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class VirtualMappingInfo:
    """Одно соответствие виртуальной и исходной областей VDS."""

    source_file: str
    source_dataset: str
    virtual_selection: str
    source_selection: str


@dataclass(frozen=True, slots=True)
class ObjectDetails:
    """Свойства и атрибуты объекта по пути HDF5."""

    path: str
    kind: ObjectKind
    object_token: str | None
    properties: tuple[tuple[str, str], ...] = ()
    attributes: tuple[AttributeInfo, ...] = ()
    references: tuple[ReferenceInfo, ...] = ()
    dimension_scales: tuple[DimensionScaleInfo, ...] = ()
    virtual_mappings: tuple[VirtualMappingInfo, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DatasetSlice:
    """Двумерное окно, спроецированное из N-мерного набора данных."""

    row_axis: int | None
    column_axis: int | None
    fixed_indices: tuple[int, ...]
    row_offset: int = 0
    column_offset: int = 0
    row_count: int = 100
    column_count: int = 50


@dataclass(slots=True)
class DatasetPage:
    """Материализованное ограниченное окно набора данных."""

    values: npt.NDArray[Any]
    row_offset: int
    column_offset: int
    row_axis_size: int
    column_axis_size: int
    dtype: str
    editable: bool
    warnings: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class DatasetCreationOptions:
    """Параметры создаваемого набора данных без зависимости от h5py."""

    shape: tuple[int, ...]
    dtype: str
    maxshape: tuple[int | None, ...] | None = None
    chunked: bool | None = None
    chunks: tuple[int, ...] | None = None
    compression: str | None = None
    compression_level: int | None = None
    fill_value_text: str | None = None
    shuffle: bool = False
    fletcher32: bool = False


@dataclass(frozen=True, slots=True)
class DatasetExtent:
    """Текущие и предельные размеры набора данных."""

    shape: tuple[int, ...]
    maxshape: tuple[int | None, ...]
    chunks: tuple[int, ...] | None


@dataclass(frozen=True, slots=True)
class ValidationReport:
    """Результат структурной проверки HDF5-файла."""

    object_count: int
    link_count: int
    warnings: tuple[str, ...] = ()


def default_dataset_slice(shape: tuple[int, ...]) -> DatasetSlice:
    """Выбрать полезную начальную двумерную проекцию."""
    ndim = len(shape)
    if ndim == 0:
        return DatasetSlice(None, None, ())
    if ndim == 1:
        return DatasetSlice(0, None, (0,))
    fixed = (0,) * ndim
    return DatasetSlice(ndim - 2, ndim - 1, fixed)


def normalize_hdf5_path(path: str) -> str:
    """Нормализовать абсолютный путь HDF5 без семантики файловой системы."""
    if not path or path == "/":
        return "/"
    parts = [part for part in path.split("/") if part]
    return "/" + "/".join(parts)


def join_hdf5_path(parent: str, name: str) -> str:
    """Соединить путь группы с именем одной ссылки HDF5."""
    parent = normalize_hdf5_path(parent)
    if parent == "/":
        return f"/{name}"
    return f"{parent}/{name}"


def split_hdf5_path(path: str) -> tuple[str, str]:
    """Разделить некорневой путь HDF5 на родительский путь и имя ссылки."""
    normalized = normalize_hdf5_path(path)
    if normalized == "/":
        raise ValueError("The root group has no parent link")
    parent, _, name = normalized.rpartition("/")
    return parent or "/", name


def scalar_to_text(value: Any) -> str:
    """Создать ограниченное и однозначное текстовое представление для UI."""
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, bytes):
        return repr(value)
    if isinstance(value, str):
        return value
    return repr(value)
