"""Адаптация стандартного hook без неиспользуемых переводов Qt."""

from __future__ import annotations

from PyInstaller.utils.hooks.qt import add_qt6_dependencies

hiddenimports, binaries, datas = add_qt6_dependencies(__file__)

# Приложение использует собственный DictionaryTranslator и не загружает *.qm Qt.
datas = [
    (source, destination)
    for source, destination in datas
    if "/translations/" not in source.replace("\\", "/")
]
