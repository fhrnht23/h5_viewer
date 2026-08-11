"""Сервис транзакционного сохранения через рабочую копию."""

from __future__ import annotations

import json
import os
import shutil
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from h5viewer.domain.errors import InsufficientSpaceError, SaveConflictError
from h5viewer.domain.models import FileFingerprint, ValidationReport

Validator = Callable[[Path], ValidationReport]


@dataclass(frozen=True, slots=True)
class WorkingCopy:
    """Пути и отпечаток оригинала для активного сеанса редактирования."""

    original_path: Path
    working_path: Path
    manifest_path: Path
    fingerprint: FileFingerprint


@dataclass(frozen=True, slots=True)
class CommitResult:
    """Сведения об успешно выполненном сохранении."""

    destination: Path
    validation: ValidationReport
    backup_path: Path | None = None


class TransactionManager:
    """Создаёт, проверяет и атомарно фиксирует рабочие копии HDF5."""

    _SPACE_MARGIN = 16 * 1024 * 1024

    def begin(self, original_path: Path) -> WorkingCopy:
        original = original_path.expanduser().resolve()
        fingerprint = FileFingerprint.from_path(original)
        free = shutil.disk_usage(original.parent).free
        required = fingerprint.size + self._SPACE_MARGIN
        if free < required:
            raise InsufficientSpaceError(
                f"Safe editing requires about {required} bytes; only {free} bytes are free"
            )
        token = uuid.uuid4().hex
        working = original.with_name(f".{original.name}.h5viewer-{token}.tmp")
        manifest = original.with_name(f".{original.name}.h5viewer-{token}.recovery.json")
        try:
            shutil.copy2(original, working)
            _fsync_file(working)
            payload = {
                "version": 1,
                "original_path": str(original),
                "working_path": str(working),
                "created_at": datetime.now(timezone.utc).isoformat(),
                "fingerprint": {
                    "size": fingerprint.size,
                    "modified_ns": fingerprint.modified_ns,
                    "inode": fingerprint.inode,
                },
            }
            manifest.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            _fsync_file(manifest)
        except Exception:
            working.unlink(missing_ok=True)
            manifest.unlink(missing_ok=True)
            raise
        return WorkingCopy(original, working, manifest, fingerprint)

    def discard(self, copy: WorkingCopy) -> None:
        copy.working_path.unlink(missing_ok=True)
        copy.manifest_path.unlink(missing_ok=True)

    def commit(
        self,
        copy: WorkingCopy,
        validator: Validator,
        *,
        create_backup: bool = True,
    ) -> CommitResult:
        current = FileFingerprint.from_path(copy.original_path)
        if current != copy.fingerprint:
            raise SaveConflictError(
                "The original file changed after editing began; "
                "use Save As to preserve both versions"
            )
        validation = validator(copy.working_path)
        _fsync_file(copy.working_path)
        backup = self._backup(copy.original_path) if create_backup else None
        os.replace(copy.working_path, copy.original_path)
        _fsync_directory(copy.original_path.parent)
        copy.manifest_path.unlink(missing_ok=True)
        return CommitResult(copy.original_path, validation, backup)

    def save_as(
        self,
        source_path: Path,
        destination_path: Path,
        validator: Validator,
        *,
        create_backup: bool = True,
    ) -> CommitResult:
        source = source_path.expanduser().resolve()
        destination = destination_path.expanduser().resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        token = uuid.uuid4().hex
        temporary = destination.with_name(f".{destination.name}.h5viewer-save-{token}.tmp")
        backup: Path | None = None
        try:
            shutil.copy2(source, temporary)
            validation = validator(temporary)
            _fsync_file(temporary)
            if destination.exists() and create_backup:
                backup = self._backup(destination)
            os.replace(temporary, destination)
            _fsync_directory(destination.parent)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
        return CommitResult(destination, validation, backup)

    def _backup(self, path: Path) -> Path:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        candidate = path.with_name(f"{path.name}.{stamp}.bak")
        suffix = 1
        while candidate.exists():
            candidate = path.with_name(f"{path.name}.{stamp}-{suffix}.bak")
            suffix += 1
        shutil.copy2(path, candidate)
        _fsync_file(candidate)
        return candidate


def _fsync_file(path: Path) -> None:
    # Windows реализует os.fsync() через _commit(), которому нужен дескриптор с правом записи.
    with path.open("rb+") as handle:
        os.fsync(handle.fileno())


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
