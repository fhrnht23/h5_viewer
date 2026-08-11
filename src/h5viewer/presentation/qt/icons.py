"""Компактные векторные значки, не зависящие от системной темы ОС."""

from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QIcon, QPainter, QPalette, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication

_PATHS = {
    "new": ('<path d="M6 3.5h7l4 4v13H6z"/><path d="M13 3.5v4h4M8.5 14h6M11.5 11v6"/>'),
    "open": ('<path d="M3.5 7.5h6l2-2h8v3"/><path d="M4.5 8.5h16l-2.5 10H6z"/>'),
    "edit": ('<path d="M5 19l1-4 9.8-9.8 3 3L9 18z"/><path d="M14.5 6.5l3 3M4.5 20h15"/>'),
    "save": ('<path d="M4 4h13l3 3v13H4z"/><path d="M8 4v6h8V4M8 20v-6h8v6"/>'),
    "discard": ('<path d="M7 7l10 10M17 7L7 17"/><circle cx="12" cy="12" r="9"/>'),
    "undo": '<path d="M9 7L4 12l5 5M5 12h8a6 6 0 0 1 6 6"/>',
    "redo": '<path d="M15 7l5 5-5 5M19 12h-8a6 6 0 0 0-6 6"/>',
    "refresh": ('<path d="M19 8V4l-2 2a8 8 0 1 0 2.2 8"/><path d="M19 4h-4"/>'),
    "copy_right": (
        '<rect x="3" y="6" width="8" height="11" rx="1.5"/>'
        '<path d="M8 3h7a2 2 0 0 1 2 2v3M14 14h7M18 11l3 3-3 3"/>'
    ),
    "copy_left": (
        '<rect x="13" y="6" width="8" height="11" rx="1.5"/>'
        '<path d="M16 3H9a2 2 0 0 0-2 2v3M10 14H3M6 11l-3 3 3 3"/>'
    ),
    "move_right": '<path d="M3 12h17M15 7l5 5-5 5"/>',
    "move_left": '<path d="M21 12H4M9 7l-5 5 5 5"/>',
    "folder": '<path d="M3 7h7l2-2h9v14H3z"/>',
    "dataset": (
        '<ellipse cx="12" cy="6" rx="8" ry="3"/>'
        '<path d="M4 6v6c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6"/>'
    ),
    "datatype": '<path d="M5 5h14M12 5v14M8 19h8"/>',
    "link": '<path d="M9.5 14.5l5-5M7 16.5H6a4 4 0 0 1 0-8h4M17 7.5h1a4 4 0 0 1 0 8h-4"/>',
    "file": '<path d="M6 3.5h7l5 5v12H6zM13 3.5v5h5"/>',
    "warning": '<path d="M12 3l10 18H2zM12 9v5M12 18v.1"/>',
}


def interface_icon(name: str, *, accent: bool = False) -> QIcon:
    """Создать значок в цвете текущей палитры приложения."""
    palette = QApplication.palette()
    role = QPalette.ColorRole.Highlight if accent else QPalette.ColorRole.Text
    color = palette.color(role).name()
    return _render_icon(name, color)


def object_icon(name: str) -> QIcon:
    """Создать спокойный акцентный значок объекта дерева."""
    color = QApplication.palette().color(QPalette.ColorRole.Highlight).name()
    return _render_icon(name, color)


@lru_cache(maxsize=64)
def _render_icon(name: str, color: str) -> QIcon:
    """Отрисовать SVG в растр повышенной плотности и закешировать результат."""
    paths = _PATHS.get(name, _PATHS["file"])
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" '
        f'viewBox="0 0 24 24" fill="none" stroke="{color}" '
        'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">'
        f"{paths}</svg>"
    )
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    pixmap = QPixmap(48, 48)
    pixmap.fill(Qt.GlobalColor.transparent)
    pixmap.setDevicePixelRatio(2.0)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    return QIcon(pixmap)
