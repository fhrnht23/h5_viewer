"""Компактное форматирование числовых значений для интерфейса."""

from __future__ import annotations

from h5viewer.presentation.qt.translations import tr


def format_byte_size(value: int | None, *, exact: bool = False) -> str:
    """Показать число байтов в двоичных единицах и при необходимости точно."""
    if value is None:
        return "—"
    units = ("B", "KiB", "MiB", "GiB", "TiB", "PiB")
    size = float(max(0, value))
    unit_index = 0
    while size >= 1024 and unit_index < len(units) - 1:
        size /= 1024
        unit_index += 1
    if unit_index == 0:
        compact = f"{value} {tr('Size', units[unit_index])}"
    else:
        number = f"{size:.1f}".rstrip("0").rstrip(".")
        if tr("Size", "B") == "Б":
            number = number.replace(".", ",")
        compact = f"{number} {tr('Size', units[unit_index])}"
    if not exact or unit_index == 0:
        return compact
    grouped = f"{value:,}".replace(",", " ")
    return f"{compact} · {grouped} {tr('Size', 'B')}"
