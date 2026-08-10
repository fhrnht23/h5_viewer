"""Не зависящие от UI команды редактирования и стек undo/redo."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from h5viewer.domain.errors import ObjectNotFoundError
from h5viewer.domain.models import join_hdf5_path
from h5viewer.domain.repository import HdfRepository


class EditCommand(ABC):
    """Обратимое логическое изменение рабочей копии HDF5."""

    label: str

    @abstractmethod
    def apply(self, repository: HdfRepository) -> None:
        """Применить или повторно применить команду."""

    @abstractmethod
    def revert(self, repository: HdfRepository) -> None:
        """Отменить команду."""


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
class MoveLinkCommand(EditCommand):
    """Переименовать или переместить одну ссылку HDF5."""

    source_path: str
    destination_path: str
    label: str = "Move link"

    def apply(self, repository: HdfRepository) -> None:
        repository.move_link(self.source_path, self.destination_path)

    def revert(self, repository: HdfRepository) -> None:
        repository.move_link(self.destination_path, self.source_path)


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

    def execute(self, command: EditCommand, repository: HdfRepository) -> None:
        if self._position < len(self._commands):
            del self._commands[self._position :]
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

    def clear(self) -> None:
        self._commands.clear()
        self._position = 0
        self._clean_position = 0

    def mark_clean(self) -> None:
        self._clean_position = self._position
