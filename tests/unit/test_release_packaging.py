"""Тесты структуры Linux AppImage перед вызовом внешнего упаковщика."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from scripts import package_linux_appimage


def test_appimage_contains_launchers_metadata_and_payload(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    source = tmp_path / "H5Viewer"
    source.mkdir()
    executable = source / "H5Viewer"
    executable.write_text("binary", encoding="utf-8")
    executable.chmod(0o755)
    (source / "_internal").mkdir()
    (source / "_internal" / "module.so").write_text("library", encoding="utf-8")
    tool = tmp_path / "appimagetool"
    tool.write_text("tool", encoding="utf-8")
    icon = tmp_path / "h5viewer.svg"
    icon.write_text("<svg/>", encoding="utf-8")
    output = tmp_path / "H5Viewer.AppImage"

    def fake_run(command: tuple[str, ...], *, check: bool, env: dict[str, str]) -> None:
        assert check
        assert env["ARCH"] == "x86_64"
        app_dir = Path(command[-2])
        assert command[1] == "--appimage-extract-and-run"
        assert os.access(app_dir / "AppRun", os.X_OK)
        assert os.access(app_dir / "usr" / "bin" / "h5viewer", os.X_OK)
        assert (app_dir / "usr" / "lib" / "h5viewer" / "H5Viewer").is_file()
        assert "Exec=h5viewer" in (app_dir / "h5viewer.desktop").read_text(encoding="utf-8")
        assert (app_dir / "h5viewer.svg").is_file()
        Path(command[-1]).write_bytes(b"appimage")

    monkeypatch.setattr(package_linux_appimage.subprocess, "run", fake_run)
    package_linux_appimage.build_appimage(source, output, tool, icon)

    assert output.read_bytes() == b"appimage"
    assert os.access(output, os.X_OK)
