"""Копирование объектов HDF5 внутри одного файла и между файлами."""

from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path

import h5py

from h5viewer.domain.errors import FileOpenError, ObjectNotFoundError, UnsupportedEditError
from h5viewer.domain.models import join_hdf5_path, normalize_hdf5_path


def copy_hdf5_object(
    source_file: Path,
    source_path: str,
    destination_file: Path,
    destination_group: str,
    destination_name: str,
) -> None:
    """Скопировать ссылку или объект без раскрытия косвенных целей."""
    source = source_file.expanduser().resolve()
    destination = destination_file.expanduser().resolve()
    source_object_path = normalize_hdf5_path(source_path)
    destination_group_path = normalize_hdf5_path(destination_group)
    if source_object_path == "/":
        raise UnsupportedEditError("Корневую группу нельзя копировать как отдельный объект")
    if not destination_name or "/" in destination_name or "\x00" in destination_name:
        raise UnsupportedEditError("Некорректное имя ссылки назначения")
    destination_path = join_hdf5_path(destination_group_path, destination_name)

    try:
        if source == destination:
            with h5py.File(destination, "r+") as h5_file:
                _copy_between_handles(
                    h5_file,
                    source_object_path,
                    h5_file,
                    destination_group_path,
                    destination_name,
                    destination_path,
                )
                h5_file.flush()
            return
        with ExitStack() as stack:
            source_handle = stack.enter_context(h5py.File(source, "r"))
            destination_handle = stack.enter_context(h5py.File(destination, "r+"))
            _copy_between_handles(
                source_handle,
                source_object_path,
                destination_handle,
                destination_group_path,
                destination_name,
                destination_path,
            )
            destination_handle.flush()
    except (FileOpenError, ObjectNotFoundError, UnsupportedEditError):
        raise
    except (KeyError, OSError, RuntimeError, ValueError) as exc:
        raise FileOpenError(f"Не удалось скопировать объект HDF5: {exc}") from exc


def _copy_between_handles(
    source_handle: h5py.File,
    source_path: str,
    destination_handle: h5py.File,
    destination_group_path: str,
    destination_name: str,
    destination_path: str,
) -> None:
    """Выполнить проверенное копирование между уже открытыми handles."""
    source_parent_path, _, source_name = source_path.rpartition("/")
    try:
        source_parent = source_handle[source_parent_path or "/"]
    except KeyError as exc:
        raise ObjectNotFoundError(f"Исходная ссылка не найдена: {source_path}") from exc
    source_link = source_parent.get(source_name, getlink=True)
    if source_link is None:
        raise ObjectNotFoundError(f"Исходная ссылка не найдена: {source_path}")
    try:
        destination_group = destination_handle[destination_group_path]
    except KeyError as exc:
        raise ObjectNotFoundError(
            f"Группа назначения не найдена: {destination_group_path}"
        ) from exc
    if not isinstance(destination_group, h5py.Group):
        raise UnsupportedEditError(f"Путь назначения не является группой: {destination_group_path}")
    if destination_group.get(destination_name, getlink=True) is not None:
        raise UnsupportedEditError(f"Ссылка назначения уже существует: {destination_path}")
    # h5py.File.copy разыменовывает сам исходный link, поэтому косвенные ссылки
    # переносим явно. Это также позволяет копировать broken soft links.
    if isinstance(source_link, h5py.SoftLink):
        destination_group[destination_name] = h5py.SoftLink(source_link.path)
        return
    if isinstance(source_link, h5py.ExternalLink):
        destination_group[destination_name] = h5py.ExternalLink(
            source_link.filename, source_link.path
        )
        return
    source_handle.copy(
        source_path,
        destination_group,
        name=destination_name,
        shallow=False,
        expand_soft=False,
        expand_external=False,
        expand_refs=False,
        without_attrs=False,
    )
