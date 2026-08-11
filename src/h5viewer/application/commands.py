"""Не зависящие от UI команды редактирования и стек undo/redo."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from h5viewer.domain.errors import ObjectNotFoundError
from h5viewer.domain.models import (
    DatasetCreationOptions,
    DatasetShrinkSnapshot,
    DeletedLinkSnapshot,
    LinkCreationOptions,
    join_hdf5_path,
)
from h5viewer.domain.repository import HdfRepository

CopyOperation = Callable[[Path, str, Path, str, str], None]


class EditCommand(ABC):
    """Обратимое логическое изменение рабочей копии HDF5."""

    label: str

    @abstractmethod
    def apply(self, repository: HdfRepository) -> None:
        """Применить или повторно применить команду."""

    @abstractmethod
    def revert(self, repository: HdfRepository) -> None:
        """Отменить команду."""

    def dispose(self) -> None:
        """Освободить внешние ресурсы команды после удаления из стека."""
        return None


@dataclass(slots=True)
class WriteDatasetValueCommand(EditCommand):
    """Изменить один элемент набора данных."""

    path: str
    index: tuple[int, ...]
    text: str
    label: str = "Edit dataset value"
    _old_value: Any = field(default=None, init=False, repr=False)
    _captured: bool = field(default=False, init=False, repr=False)

    def apply(self, repository: HdfRepository) -> None:
        if not self._captured:
            self._old_value = repository.read_dataset_value(self.path, self.index)
            self._captured = True
        repository.write_dataset_value(self.path, self.index, self.text)

    def revert(self, repository: HdfRepository) -> None:
        repository.write_dataset_value_raw(self.path, self.index, self._old_value)


@dataclass(slots=True)
class SetAttributeCommand(EditCommand):
    """Создать или изменить атрибут."""

    path: str
    name: str
    text: str
    label: str = "Set attribute"
    _old_value: Any = field(default=None, init=False, repr=False)
    _existed: bool = field(default=False, init=False, repr=False)
    _captured: bool = field(default=False, init=False, repr=False)

    def apply(self, repository: HdfRepository) -> None:
        if not self._captured:
            try:
                self._old_value = repository.read_attribute_value(self.path, self.name)
            except ObjectNotFoundError:
                self._existed = False
            else:
                self._existed = True
            self._captured = True
        repository.set_attribute(self.path, self.name, self.text)

    def revert(self, repository: HdfRepository) -> None:
        if self._existed:
            repository.write_attribute_value_raw(self.path, self.name, self._old_value)
        else:
            repository.delete_attribute(self.path, self.name)


@dataclass(slots=True)
class DeleteAttributeCommand(EditCommand):
    """Удалить атрибут, сохранив его значение для отмены."""

    path: str
    name: str
    label: str = "Delete attribute"
    _old_value: Any = field(default=None, init=False, repr=False)
    _captured: bool = field(default=False, init=False, repr=False)

    def apply(self, repository: HdfRepository) -> None:
        if not self._captured:
            self._old_value = repository.read_attribute_value(self.path, self.name)
            self._captured = True
        repository.delete_attribute(self.path, self.name)

    def revert(self, repository: HdfRepository) -> None:
        repository.write_attribute_value_raw(self.path, self.name, self._old_value)


@dataclass(slots=True)
class CreateGroupCommand(EditCommand):
    """Создать пустую группу."""

    parent_path: str
    name: str
    label: str = "Create group"

    @property
    def created_path(self) -> str:
        return join_hdf5_path(self.parent_path, self.name)

    def apply(self, repository: HdfRepository) -> None:
        repository.create_group(self.parent_path, self.name)

    def revert(self, repository: HdfRepository) -> None:
        repository.delete_link(self.created_path)


@dataclass(slots=True)
class CreateDatasetCommand(EditCommand):
    """Создать пустой набор данных с заданными свойствами хранения."""

    parent_path: str
    name: str
    options: DatasetCreationOptions
    label: str = "Create dataset"

    @property
    def created_path(self) -> str:
        return join_hdf5_path(self.parent_path, self.name)

    def apply(self, repository: HdfRepository) -> None:
        repository.create_dataset(self.parent_path, self.name, self.options)

    def revert(self, repository: HdfRepository) -> None:
        repository.delete_link(self.created_path)


@dataclass(slots=True)
class ResizeDatasetCommand(EditCommand):
    """Изменить размер dataset с точным undo, включая дисковый снимок при уменьшении."""

    path: str
    new_shape: tuple[int, ...]
    label: str = "Resize dataset"
    _old_shape: tuple[int, ...] | None = field(default=None, init=False, repr=False)
    _snapshot: DatasetShrinkSnapshot | None = field(default=None, init=False, repr=False)

    def apply(self, repository: HdfRepository) -> None:
        if self._old_shape is None:
            self._old_shape = repository.dataset_extent(self.path).shape
        shrinking = len(self._old_shape) == len(self.new_shape) and any(
            new < old for old, new in zip(self._old_shape, self.new_shape, strict=True)
        )
        if shrinking:
            self._snapshot = repository.shrink_dataset_with_snapshot(self.path, self.new_shape)
        else:
            repository.resize_dataset(self.path, self.new_shape)

    def revert(self, repository: HdfRepository) -> None:
        if self._old_shape is None:
            raise RuntimeError("Исходный размер dataset не был сохранён")
        if self._snapshot is not None:
            repository.restore_dataset_shrink_snapshot(self._snapshot)
            # Снимок перемещён на место рабочей копии; при redo он будет создан заново.
            self._snapshot = None
        else:
            # Стек команд гарантирует, что изменения в добавленной области уже отменены.
            repository.resize_dataset(self.path, self._old_shape, allow_shrink=True)

    def dispose(self) -> None:
        if self._snapshot is not None:
            self._snapshot.backup_path.unlink(missing_ok=True)


@dataclass(slots=True)
class CreateLinkCommand(EditCommand):
    """Создать HDF5-ссылку одного из поддерживаемых видов."""

    parent_path: str
    name: str
    options: LinkCreationOptions
    label: str = "Create link"

    @property
    def created_path(self) -> str:
        return join_hdf5_path(self.parent_path, self.name)

    def apply(self, repository: HdfRepository) -> None:
        repository.create_link(self.parent_path, self.name, self.options)

    def revert(self, repository: HdfRepository) -> None:
        repository.delete_link(self.created_path)


@dataclass(slots=True)
class DeleteLinkCommand(EditCommand):
    """Удалить ссылку с дисковым snapshot для безопасного undo."""

    path: str
    label: str = "Delete link"
    _snapshot: DeletedLinkSnapshot | None = field(default=None, init=False, repr=False)

    def apply(self, repository: HdfRepository) -> None:
        if self._snapshot is None:
            self._snapshot = repository.delete_link_with_snapshot(self.path)
        else:
            repository.delete_link(self.path)

    def revert(self, repository: HdfRepository) -> None:
        if self._snapshot is None:
            raise RuntimeError("Snapshot удалённой ссылки не был создан")
        repository.restore_deleted_link(self.path, self._snapshot)

    def dispose(self) -> None:
        if self._snapshot is not None and self._snapshot.backup_path is not None:
            self._snapshot.backup_path.unlink(missing_ok=True)


@dataclass(slots=True)
class MoveLinkCommand(EditCommand):
    """Переименовать или переместить одну ссылку HDF5."""

    source_path: str
    destination_path: str
    label: str = "Move link"

    def apply(self, repository: HdfRepository) -> None:
        repository.move_link(self.source_path, self.destination_path)

    def revert(self, repository: HdfRepository) -> None:
        repository.move_link(self.destination_path, self.source_path)


@dataclass(slots=True)
class CopyObjectCommand(EditCommand):
    """Скопировать объект или ссылку в рабочий файл назначения."""

    source_file: Path
    source_path: str
    destination_group: str
    destination_name: str
    copy_operation: CopyOperation = field(repr=False)
    label: str = "Copy object"

    @property
    def destination_path(self) -> str:
        return join_hdf5_path(self.destination_group, self.destination_name)

    def apply(self, repository: HdfRepository) -> None:
        self.copy_operation(
            self.source_file,
            self.source_path,
            repository.path,
            self.destination_group,
            self.destination_name,
        )

    def revert(self, repository: HdfRepository) -> None:
        repository.delete_link(self.destination_path)


class CommandStack:
    """Небольшой стек команд уровня приложения, не зависящий от Qt."""

    def __init__(self) -> None:
        self._commands: list[EditCommand] = []
        self._position = 0
        self._clean_position = 0

    @property
    def can_undo(self) -> bool:
        return self._position > 0

    @property
    def can_redo(self) -> bool:
        return self._position < len(self._commands)

    @property
    def is_dirty(self) -> bool:
        return self._position != self._clean_position

    @property
    def undo_label(self) -> str | None:
        return self._commands[self._position - 1].label if self.can_undo else None

    @property
    def redo_label(self) -> str | None:
        return self._commands[self._position].label if self.can_redo else None

    def is_next_undo(self, command: EditCommand) -> bool:
        """Проверить идентичность следующей команды undo."""
        return self.can_undo and self._commands[self._position - 1] is command

    def is_next_redo(self, command: EditCommand) -> bool:
        """Проверить идентичность следующей команды redo."""
        return self.can_redo and self._commands[self._position] is command

    def execute(self, command: EditCommand, repository: HdfRepository) -> None:
        if self._position < len(self._commands):
            removed = self._commands[self._position :]
            del self._commands[self._position :]
            for discarded in removed:
                discarded.dispose()
            if self._clean_position > self._position:
                self._clean_position = -1
        command.apply(repository)
        self._commands.append(command)
        self._position += 1

    def undo(self, repository: HdfRepository) -> None:
        if not self.can_undo:
            return
        command = self._commands[self._position - 1]
        command.revert(repository)
        self._position -= 1

    def redo(self, repository: HdfRepository) -> None:
        if not self.can_redo:
            return
        command = self._commands[self._position]
        command.apply(repository)
        self._position += 1

    def discard_redo(self) -> None:
        """Удалить redo-ветку после отката неудачной составной операции."""
        if self._position >= len(self._commands):
            return
        removed = self._commands[self._position :]
        del self._commands[self._position :]
        for command in removed:
            command.dispose()
        if self._clean_position > self._position:
            self._clean_position = -1

    def clear(self) -> None:
        for command in self._commands:
            command.dispose()
        self._commands.clear()
        self._position = 0
        self._clean_position = 0

    def mark_clean(self) -> None:
        self._clean_position = self._position
