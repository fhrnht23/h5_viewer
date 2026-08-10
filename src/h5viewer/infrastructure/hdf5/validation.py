"""Изолированный запуск структурной проверки HDF5-файла."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from h5viewer.domain.errors import ValidationError
from h5viewer.domain.models import ValidationReport


def validate_hdf5_in_subprocess(
    path: Path | str,
    *,
    timeout_seconds: float = 120.0,
) -> ValidationReport:
    """Проверить файл отдельным процессом и вернуть сериализованный отчёт."""
    candidate = Path(path).expanduser().resolve()
    command = [
        sys.executable,
        "-m",
        "h5viewer.infrastructure.hdf5.validation_worker",
        str(candidate),
    ]
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        raise ValidationError(
            f"Проверка HDF5-файла не завершилась за {timeout_seconds:g} секунд"
        ) from exc
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "неизвестная ошибка"
        raise ValidationError(f"Изолированная проверка HDF5 завершилась ошибкой: {detail}")
    try:
        payload: dict[str, Any] = json.loads(completed.stdout)
        return ValidationReport(
            object_count=int(payload["object_count"]),
            link_count=int(payload["link_count"]),
            warnings=tuple(str(value) for value in payload.get("warnings", [])),
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValidationError("Процесс проверки вернул некорректный отчёт") from exc
