"""Сеанс документа, координирующий репозитории, команды и безопасное сохранение."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from pathlib import Path

from h5viewer.application.commands import CommandStack, EditCommand
from h5viewer.application.transaction import CommitResult, TransactionManager, WorkingCopy
from h5viewer.domain.errors import UnsupportedEditError
from h5viewer.domain.models import FileFingerprint, ValidationReport
from h5viewer.domain.repository import HdfRepository

RepositoryFactory = Callable[[Path, bool], HdfRepository]
FileValidator = Callable[[Path], ValidationReport]


class DocumentSession:
    """Один логический документ, совместно используемый несколькими панелями UI."""

    def __init__(
        self,
        path: Path | str,
        repository_factory: RepositoryFactory,
        transaction_manager: TransactionManager | None = None,
        file_validator: FileValidator | None = None,
    ) -> None:
        self.document_id = uuid.uuid4().hex
        self._original_path = Path(path).expanduser().resolve()
        self._factory = repository_factory
        self._transactions = transaction_manager or TransactionManager()
        self._validator = file_validator or (
            lambda candidate: self._factory(candidate, False).validate()
        )
        self._working_copy: WorkingCopy | None = None
        self._fingerprint = FileFingerprint.from_path(self._original_path)
        self.commands = CommandStack()
        self._factory(self._original_path, False).root()

    @property
    def original_path(self) -> Path:
        return self._original_path

    @property
    def active_path(self) -> Path:
        if self._working_copy is not None:
            return self._working_copy.working_path
        return self._original_path

    @property
    def is_editing(self) -> bool:
        return self._working_copy is not None

    @property
    def is_dirty(self) -> bool:
        return self.commands.is_dirty

    @property
    def externally_modified(self) -> bool:
        try:
            return FileFingerprint.from_path(self._original_path) != self._fingerprint
        except FileNotFoundError:
            return True

    def repository(self) -> HdfRepository:
        return self._factory(self.active_path, self.is_editing)

    def begin_edit(self) -> None:
        if self._working_copy is not None:
            return
        self._working_copy = self._transactions.begin(self._original_path)
        self.commands.clear()

    def execute(self, command: EditCommand) -> None:
        if not self.is_editing:
            raise UnsupportedEditError("Enable safe editing before changing the file")
        self.commands.execute(command, self.repository())

    def undo(self) -> None:
        if not self.is_editing:
            return
        self.commands.undo(self.repository())

    def redo(self) -> None:
        if not self.is_editing:
            return
        self.commands.redo(self.repository())

    def save(self, *, create_backup: bool = True) -> CommitResult | None:
        if self._working_copy is None:
            return None
        result = self._transactions.commit(
            self._working_copy,
            self._validator,
            create_backup=create_backup,
        )
        self._working_copy = None
        self._fingerprint = FileFingerprint.from_path(self._original_path)
        self.commands.clear()
        return result

    def save_as(self, destination: Path | str, *, create_backup: bool = True) -> CommitResult:
        target = Path(destination).expanduser().resolve()
        if target == self._original_path and self._working_copy is not None:
            result = self.save(create_backup=create_backup)
            if result is None:
                raise RuntimeError("Unexpected empty save result")
            return result
        result = self._transactions.save_as(
            self.active_path,
            target,
            self._validator,
            create_backup=create_backup,
        )
        if self._working_copy is not None:
            self._transactions.discard(self._working_copy)
            self._working_copy = None
        self._original_path = target
        self._fingerprint = FileFingerprint.from_path(target)
        self.commands.clear()
        return result

    def discard(self) -> None:
        if self._working_copy is not None:
            self._transactions.discard(self._working_copy)
            self._working_copy = None
        self.commands.clear()

    def reload(self) -> None:
        if self.is_dirty:
            raise UnsupportedEditError("Discard or save pending changes before reloading")
        if self._working_copy is not None:
            self.discard()
        self._factory(self._original_path, False).root()
        self._fingerprint = FileFingerprint.from_path(self._original_path)
