"""Единый набор качественных векторных значков интерфейса."""

from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPalette, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication

# Контуры взяты из Tabler Icons 3.44.0 (MIT) и хранятся внутри пакета,
# чтобы значки одинаково отображались на всех платформах и без доступа к сети.
_PATHS = {
    "new": (
        '<path d="M14 3v4a1 1 0 0 0 1 1h4"/>'
        '<path d="M17 21h-10a2 2 0 0 1 -2 -2v-14a2 2 0 0 1 2 -2h7l5 5v11'
        'a2 2 0 0 1 -2 2"/>'
        '<path d="M12 11v6M9 14h6"/>'
    ),
    "open": (
        '<path d="M5 19l2.757 -7.351a1 1 0 0 1 .936 -.649h12.307a1 1 0 0 1 '
        ".986 1.164l-.996 5.211a2 2 0 0 1 -1.964 1.625h-14.026a2 2 0 0 1 -2 -2v-11"
        'a2 2 0 0 1 2 -2h4l3 3h7a2 2 0 0 1 2 2v2"/>'
    ),
    "edit": (
        '<path d="M4 20h4l10.5 -10.5a2.828 2.828 0 1 0 -4 -4l-10.5 10.5v4"/>'
        '<path d="M13.5 6.5l4 4"/>'
    ),
    "save": (
        '<path d="M6 4h10l4 4v10a2 2 0 0 1 -2 2h-12a2 2 0 0 1 -2 -2v-12'
        'a2 2 0 0 1 2 -2"/>'
        '<path d="M10 14a2 2 0 1 0 4 0a2 2 0 1 0 -4 0M14 4v4H8V4"/>'
    ),
    "discard": (
        '<path d="M14 3v4a1 1 0 0 0 1 1h4"/>'
        '<path d="M17 21h-10a2 2 0 0 1 -2 -2v-14a2 2 0 0 1 2 -2h7l5 5v11'
        'a2 2 0 0 1 -2 2"/>'
        '<path d="M10 12l4 4M14 12l-4 4"/>'
    ),
    "undo": '<path d="M9 14l-4 -4l4 -4M5 10h11a4 4 0 1 1 0 8h-1"/>',
    "redo": '<path d="M15 14l4 -4l-4 -4M19 10H8a4 4 0 1 0 0 8h1"/>',
    "refresh": (
        '<path d="M20 11a8.1 8.1 0 0 0 -15.5 -2M4 5v4h4"/>'
        '<path d="M4 13a8.1 8.1 0 0 0 15.5 2M20 19v-4h-4"/>'
    ),
    "copy_right": (
        '<path d="M7 9.667A2.667 2.667 0 0 1 9.667 7h8.666A2.667 2.667 0 0 1 21 '
        "9.667v8.666A2.667 2.667 0 0 1 18.333 21H9.667A2.667 2.667 0 0 1 7 "
        '18.333z"/>'
        '<path d="M4.012 16.737A2.005 2.005 0 0 1 3 15V5c0 -1.1 .9 -2 2 -2h10'
        'c.75 0 1.158 .385 1.5 1"/>'
    ),
    "copy_left": (
        '<path d="M7 9.667A2.667 2.667 0 0 1 9.667 7h8.666A2.667 2.667 0 0 1 21 '
        "9.667v8.666A2.667 2.667 0 0 1 18.333 21H9.667A2.667 2.667 0 0 1 7 "
        '18.333z"/>'
        '<path d="M4.012 16.737A2.005 2.005 0 0 1 3 15V5c0 -1.1 .9 -2 2 -2h10'
        'c.75 0 1.158 .385 1.5 1"/>'
    ),
    "move_right": '<path d="M5 12h14M13 18l6 -6M13 6l6 6"/>',
    "move_left": '<path d="M5 12h14M5 12l6 6M5 12l6 -6"/>',
    "folder": (
        '<path d="M5 4h4l3 3h7a2 2 0 0 1 2 2v8a2 2 0 0 1 -2 2h-14'
        'a2 2 0 0 1 -2 -2v-11a2 2 0 0 1 2 -2"/>'
    ),
    "dataset": (
        '<path d="M4 6a8 3 0 1 0 16 0a8 3 0 1 0 -16 0"/>'
        '<path d="M4 6v6a8 3 0 0 0 16 0V6M4 12v6a8 3 0 0 0 16 0v-6"/>'
    ),
    "datatype": ('<path d="M4 20h3M14 20h7M6.9 15h6.9M10.2 6.3L16 20M5 20l6 -16h2l7 16"/>'),
    "link": (
        '<path d="M9 15l6 -6M11 6l.463 -.536a5 5 0 0 1 7.071 7.072L18 13"/>'
        '<path d="M13 18l-.397 .534a5.068 5.068 0 0 1 -7.127 0a4.972 4.972 0 0 1 '
        '0 -7.071L6 11"/>'
    ),
    "file": (
        '<path d="M14 3v4a1 1 0 0 0 1 1h4"/>'
        '<path d="M17 21h-10a2 2 0 0 1 -2 -2v-14a2 2 0 0 1 2 -2h7l5 5v11'
        'a2 2 0 0 1 -2 2"/>'
    ),
    "warning": (
        '<path d="M12 9v4M12 16h.01"/>'
        '<path d="M10.363 3.591L2.257 17.125a1.914 1.914 0 0 0 1.636 2.871h16.214'
        'a1.914 1.914 0 0 0 1.636 -2.87L13.637 3.59a1.914 1.914 0 0 0 -3.274 0"/>'
    ),
    "settings": (
        '<path d="M10.325 4.317c.426 -1.756 2.924 -1.756 3.35 0a1.724 1.724 0 0 0 '
        "2.573 1.066c1.543 -.94 3.31 .826 2.37 2.37a1.724 1.724 0 0 0 1.065 "
        "2.572c1.756 .426 1.756 2.924 0 3.35a1.724 1.724 0 0 0 -1.066 2.573"
        "c.94 1.543 -.826 3.31 -2.37 2.37a1.724 1.724 0 0 0 -2.572 1.065"
        "c-.426 1.756 -2.924 1.756 -3.35 0a1.724 1.724 0 0 0 -2.573 -1.066"
        "c-1.543 .94 -3.31 -.826 -2.37 -2.37a1.724 1.724 0 0 0 -1.065 -2.572"
        "c-1.756 -.426 -1.756 -2.924 0 -3.35a1.724 1.724 0 0 0 1.066 -2.573"
        'c-.94 -1.543 .826 -3.31 2.37 -2.37c1 .608 2.296 .07 2.572 -1.065"/>'
        '<path d="M9 12a3 3 0 1 0 6 0a3 3 0 0 0 -6 0"/>'
    ),
    "search": '<path d="M3 10a7 7 0 1 0 14 0a7 7 0 1 0 -14 0M21 21l-6 -6"/>',
    "up": '<path d="M6 15l6 -6l6 6"/>',
    "tree": ('<path d="M12 3v5M5 21v-4M12 21v-4M19 21v-4"/><path d="M5 17v-4h14v4M12 8v5"/>'),
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
        'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        f"{paths}</svg>"
    )
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    pixmap = QPixmap(72, 72)
    pixmap.fill(Qt.GlobalColor.transparent)
    pixmap.setDevicePixelRatio(3.0)
    painter = QPainter(pixmap)
    renderer.render(painter, QRectF(0.0, 0.0, 24.0, 24.0))
    painter.end()
    return QIcon(pixmap)
