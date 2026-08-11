"""Пример плагина со сводкой выбранного HDF5-объекта."""

from __future__ import annotations

from h5viewer.plugins import (
    API_VERSION,
    LocalizedText,
    Plugin,
    PluginHost,
    PluginRegistration,
)


class ObjectSummaryPlugin:
    """Добавляет в меню инструментов команду с информацией о выборе."""

    plugin_id = "org.h5viewer.example.object-summary"
    display_name = "Object Summary"
    api_version = API_VERSION

    def __init__(self) -> None:
        self._registration: PluginRegistration | None = None

    def activate(self, host: PluginHost) -> None:
        self._registration = host.add_tools_action(
            self.plugin_id,
            "show-selection",
            LocalizedText("Сводка выбранного объекта…", "Selected object summary…"),
            lambda: self._show_selection(host),
        )

    def deactivate(self) -> None:
        if self._registration is not None:
            self._registration.remove()
            self._registration = None

    @staticmethod
    def _show_selection(host: PluginHost) -> None:
        selection = host.current_selection()
        title = LocalizedText("Сводка объекта", "Object summary")
        if selection is None:
            host.show_information(
                title,
                LocalizedText("Объект не выбран.", "No object is selected."),
            )
            return
        host.show_information(
            title,
            LocalizedText(
                "\n".join(
                    (
                        f"Файл: {selection.document_path}",
                        f"Путь: {selection.object_path}",
                        f"Тип объекта: {selection.object_kind}",
                        f"Тип ссылки: {selection.link_kind}",
                    )
                ),
                "\n".join(
                    (
                        f"File: {selection.document_path}",
                        f"Path: {selection.object_path}",
                        f"Object kind: {selection.object_kind}",
                        f"Link kind: {selection.link_kind}",
                    )
                ),
            ),
        )


def create_plugin() -> Plugin:
    """Создать новый экземпляр для загрузчика entry points."""
    return ObjectSummaryPlugin()
