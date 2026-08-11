"""Сборка самостоятельного desktop-пакета для текущей операционной системы."""

from __future__ import annotations

import importlib.util
import plistlib
import subprocess
import sys
import tempfile
from pathlib import Path

import PyInstaller.__main__

from h5viewer import __version__


def main() -> None:
    """Запустить PyInstaller с едиными параметрами проекта."""
    project_root = Path(__file__).resolve().parents[1]
    if importlib.util.find_spec("pyqtgraph") is None:
        raise RuntimeError("Для desktop-сборки установите дополнение проекта 'packaging'")
    temporary_dist: tempfile.TemporaryDirectory[str] | None = None
    if sys.platform == "darwin":
        # Сборка вне синхронизируемых каталогов не получает запрещённые FinderInfo xattrs.
        temporary_dist = tempfile.TemporaryDirectory(prefix="h5viewer-macos-dist-")
        dist_path = Path(temporary_dist.name)
    else:
        dist_path = project_root / "dist"
    arguments = [
        str(project_root / "src" / "h5viewer" / "__main__.py"),
        "--name",
        "H5Viewer",
        "--windowed",
        "--onedir",
        "--clean",
        "--noconfirm",
        "--paths",
        str(project_root / "src"),
        "--additional-hooks-dir",
        str(project_root / "scripts" / "pyinstaller_hooks"),
        "--hidden-import",
        "pyqtgraph",
        "--distpath",
        str(dist_path),
        "--workpath",
        str(project_root / "build" / "pyinstaller"),
        "--specpath",
        str(project_root / "build" / "pyinstaller"),
    ]
    if sys.platform == "darwin":
        arguments.extend(("--osx-bundle-identifier", "org.h5viewer.desktop"))
    try:
        PyInstaller.__main__.run(arguments)
        if sys.platform == "darwin":
            _prepare_macos_bundle(
                dist_path / "H5Viewer.app",
                project_root / "dist" / "H5Viewer-macOS.zip",
            )
    finally:
        if temporary_dist is not None:
            temporary_dist.cleanup()


def _prepare_macos_bundle(bundle: Path, archive: Path) -> None:
    """Записать версию, подписать bundle и упаковать его без посторонних xattrs."""
    plist_path = bundle / "Contents" / "Info.plist"
    with plist_path.open("rb") as stream:
        information = plistlib.load(stream)
    information["CFBundleShortVersionString"] = __version__
    information["CFBundleVersion"] = __version__
    with plist_path.open("wb") as stream:
        plistlib.dump(information, stream)
    subprocess.run(("xattr", "-cr", str(bundle)), check=True)
    subprocess.run(("codesign", "--force", "--deep", "--sign", "-", str(bundle)), check=True)
    subprocess.run(("codesign", "--verify", "--deep", "--strict", str(bundle)), check=True)
    archive.parent.mkdir(parents=True, exist_ok=True)
    archive.unlink(missing_ok=True)
    subprocess.run(
        ("ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", str(bundle), str(archive)),
        check=True,
    )


if __name__ == "__main__":
    main()
