"""Подготовка платформенных компонентов Qt для проблемных сред."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import QLibraryInfo

_platform_plugin_aliases: tempfile.TemporaryDirectory[str] | None = None


def prepare_qt_platform_plugins() -> None:
    """Создать совместимые псевдонимы Qt-плагинов для новых версий macOS.

    Некоторые macOS-сборки Qt 6 поставляют платформенные плагины как ``.dylib``,
    но загрузчик ищет только ``.so``. Символические ссылки создаются во временном
    каталоге и не изменяют установленный пакет PySide6.
    """
    global _platform_plugin_aliases

    if sys.platform != "darwin" or _platform_plugin_aliases is not None:
        return

    plugin_root = Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.PluginsPath))
    platform_directory = plugin_root / "platforms"
    dylib_plugins = tuple(platform_directory.glob("*.dylib"))
    if not dylib_plugins or tuple(platform_directory.glob("*.so")):
        return

    aliases = tempfile.TemporaryDirectory(prefix="h5viewer-qt-platforms-")
    alias_directory = Path(aliases.name)
    try:
        for plugin in dylib_plugins:
            alias_name = f"{plugin.stem}.so"
            (alias_directory / alias_name).symlink_to(plugin.resolve())
    except OSError:
        aliases.cleanup()
        raise

    os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = str(alias_directory)
    _platform_plugin_aliases = aliases
