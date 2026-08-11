"""Изолированный запуск структурной проверки HDF5-файла."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
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
    report_path: Path | None = None
    if getattr(sys, "frozen", False):
        descriptor, report_name = tempfile.mkstemp(prefix="h5viewer-validation-", suffix=".json")
        os.close(descriptor)
        report_path = Path(report_name)
        command = [sys.executable, "--validate-worker", str(candidate), str(report_path)]
    else:
        command = [
            sys.executable,
            "-m",
            "h5viewer.infrastructure.hdf5.validation_worker",
            str(candidate),
        ]
    try:
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
        file_output = report_path.read_text(encoding="utf-8") if report_path is not None else ""
        if completed.returncode != 0:
            detail = (
                file_output.strip()
                or completed.stderr.strip()
                or completed.stdout.strip()
                or "неизвестная ошибка"
            )
            raise ValidationError(f"Изолированная проверка HDF5 завершилась ошибкой: {detail}")
        payload: dict[str, Any] = json.loads(file_output or completed.stdout)
        return ValidationReport(
            object_count=int(payload["object_count"]),
            link_count=int(payload["link_count"]),
            warnings=tuple(str(value) for value in payload.get("warnings", [])),
        )
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValidationError("Процесс проверки вернул некорректный отчёт") from exc
    finally:
        if report_path is not None:
            report_path.unlink(missing_ok=True)
