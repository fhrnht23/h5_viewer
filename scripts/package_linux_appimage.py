"""Упаковка готового каталога PyInstaller в переносимый Linux AppImage."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import tempfile
from pathlib import Path


def build_appimage(source: Path, output: Path, tool: Path, icon: Path) -> None:
    """Создать AppDir, собрать AppImage и сохранить его по указанному пути."""
    source = source.resolve()
    tool = tool.resolve()
    icon = icon.resolve()
    if not (source / "H5Viewer").is_file():
        raise FileNotFoundError(f"Не найден исполняемый файл PyInstaller: {source / 'H5Viewer'}")
    if not tool.is_file():
        raise FileNotFoundError(f"Не найден appimagetool: {tool}")
    if not icon.is_file():
        raise FileNotFoundError(f"Не найден значок приложения: {icon}")

    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.unlink(missing_ok=True)
    with tempfile.TemporaryDirectory(prefix="h5viewer-appimage-") as temporary:
        app_dir = Path(temporary) / "H5Viewer.AppDir"
        payload = app_dir / "usr" / "lib" / "h5viewer"
        shutil.copytree(source, payload)

        launcher = app_dir / "AppRun"
        launcher.write_text(
            '#!/bin/sh\nHERE="$(dirname "$(readlink -f "$0")")"\n'
            'exec "$HERE/usr/lib/h5viewer/H5Viewer" "$@"\n',
            encoding="utf-8",
        )
        launcher.chmod(0o755)

        bin_dir = app_dir / "usr" / "bin"
        bin_dir.mkdir(parents=True)
        command = bin_dir / "h5viewer"
        command.write_text(
            '#!/bin/sh\nHERE="$(dirname "$(readlink -f "$0")")"\n'
            'exec "$HERE/../lib/h5viewer/H5Viewer" "$@"\n',
            encoding="utf-8",
        )
        command.chmod(0o755)

        desktop = app_dir / "h5viewer.desktop"
        desktop.write_text(
            "[Desktop Entry]\n"
            "Type=Application\n"
            "Name=H5 Viewer\n"
            "Comment=Two-pane HDF5 viewer and safe editor\n"
            "Exec=h5viewer\n"
            "Icon=h5viewer\n"
            "Categories=Utility;Science;\n"
            "Terminal=false\n",
            encoding="utf-8",
        )
        applications = app_dir / "usr" / "share" / "applications"
        applications.mkdir(parents=True)
        shutil.copy2(desktop, applications / desktop.name)
        shutil.copy2(icon, app_dir / "h5viewer.svg")
        icon_dir = app_dir / "usr" / "share" / "icons" / "hicolor" / "scalable" / "apps"
        icon_dir.mkdir(parents=True)
        shutil.copy2(icon, icon_dir / "h5viewer.svg")

        environment = os.environ.copy()
        environment["ARCH"] = "x86_64"
        subprocess.run(
            (str(tool), "--appimage-extract-and-run", str(app_dir), str(output)),
            check=True,
            env=environment,
        )
    output.chmod(0o755)


def main() -> None:
    """Разобрать параметры командной строки и запустить упаковку."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--tool", required=True, type=Path)
    parser.add_argument(
        "--icon",
        type=Path,
        default=Path("packaging/linux/h5viewer.svg"),
    )
    arguments = parser.parse_args()
    build_appimage(arguments.source, arguments.output, arguments.tool, arguments.icon)


if __name__ == "__main__":
    main()
