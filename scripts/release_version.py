"""Проверка согласованности Git-тега и версии собираемого пакета."""

from __future__ import annotations

import argparse
import importlib.metadata
from pathlib import Path

from h5viewer import __version__


def release_version(tag: str) -> str:
    """Вернуть версию релиза или сообщить о несовпадении источников версии."""
    normalized = tag.removeprefix("v")
    distribution_version = importlib.metadata.version("h5viewer")
    versions = {
        "Git-тег": normalized,
        "h5viewer.__version__": __version__,
        "метаданные пакета": distribution_version,
    }
    if len(set(versions.values())) != 1:
        details = ", ".join(f"{name}={value}" for name, value in versions.items())
        raise ValueError(f"Версии релиза не совпадают: {details}")
    return normalized


def main() -> None:
    """Проверить тег и записать версию в выход GitHub Actions."""
    parser = argparse.ArgumentParser()
    parser.add_argument("tag", help="Git-тег выпуска, например v0.1.0")
    parser.add_argument(
        "--github-output",
        type=Path,
        help="Файл GITHUB_OUTPUT; без него версия печатается в stdout",
    )
    arguments = parser.parse_args()
    version = release_version(arguments.tag)
    if arguments.github_output is None:
        print(version)
        return
    with arguments.github_output.open("a", encoding="utf-8") as output:
        output.write(f"version={version}\n")


if __name__ == "__main__":
    main()
