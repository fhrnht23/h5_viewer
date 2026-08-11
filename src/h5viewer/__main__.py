"""Точка входа приложения."""

from __future__ import annotations

import sys


def main() -> int:
    """Запустить Qt-приложение."""
    if len(sys.argv) >= 2 and sys.argv[1] == "--validate-worker":
        from h5viewer.infrastructure.hdf5.validation_worker import main as validation_main

        return validation_main(sys.argv[2:])
    from h5viewer.presentation.qt.app import run

    return run(sys.argv)


if __name__ == "__main__":
    raise SystemExit(main())
