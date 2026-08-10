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
    if len(values) != 1:
        print("Ожидается ровно один путь к HDF5-файлу", file=sys.stderr)
        return 2
    try:
        report = H5pyRepository(Path(values[0])).validate()
    except Exception as exc:
        # Граница процесса обязана преобразовать любую ошибку в безопасный exit code.
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    payload: dict[str, Any] = {
        "object_count": report.object_count,
        "link_count": report.link_count,
        "warnings": list(report.warnings),
    }
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
