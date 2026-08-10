"""Точка входа приложения."""

from __future__ import annotations

import sys


def main() -> int:
    """Запустить Qt-приложение."""
    from h5viewer.presentation.qt.app import run

    return run(sys.argv)


if __name__ == "__main__":
    raise SystemExit(main())
