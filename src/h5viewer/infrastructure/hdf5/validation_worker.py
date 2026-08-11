"""Минимальная CLI-точка входа изолированной проверки HDF5."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from h5viewer.infrastructure.hdf5.h5py_repository import H5pyRepository


def main(arguments: list[str] | None = None) -> int:
    """Проверить один файл и напечатать JSON-отчёт в stdout."""
    values = list(sys.argv[1:] if arguments is None else arguments)
    if len(values) not in {1, 2}:
        print("Ожидается ровно один путь к HDF5-файлу", file=sys.stderr)
        return 2
    output_path = Path(values[1]) if len(values) == 2 else None
    try:
        report = H5pyRepository(Path(values[0])).validate()
    except Exception as exc:
        # Граница процесса обязана преобразовать любую ошибку в безопасный exit code.
        _emit(f"{type(exc).__name__}: {exc}", output_path, error=True)
        return 1
    payload: dict[str, Any] = {
        "object_count": report.object_count,
        "link_count": report.link_count,
        "warnings": list(report.warnings),
    }
    _emit(json.dumps(payload, ensure_ascii=False), output_path)
    return 0


def _emit(text: str, output_path: Path | None, *, error: bool = False) -> None:
    """Передать результат через файл для windowed binary либо через стандартный поток."""
    if output_path is not None:
        output_path.write_text(text, encoding="utf-8")
        return
    print(text, file=sys.stderr if error else sys.stdout)


if __name__ == "__main__":
    raise SystemExit(main())
