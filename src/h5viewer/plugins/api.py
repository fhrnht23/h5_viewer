"""Стабильные типы API расширений, не зависящие от Qt и h5py."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

API_VERSION = 1
ENTRY_POINT_GROUP = "h5viewer.plugins"


@dataclass(frozen=True, slots=True)
class LocalizedText:
    """Русский и английский варианты одной пользовательской строки."""

    russian: str
    english: str

    def resolve(self, language: str) -> str:
        """Выбрать строку для текущего языка приложения."""
        return self.russian if language.lower().startswith("ru") else self.english


@dataclass(frozen=True, slots=True)
class ObjectSelection:
    """Безопасный снимок текущего выбора без внутренних объектов приложения."""

    document_path: Path
    object_path: str
    object_kind: str
    link_kind: str
    editing: bool


@runtime_checkable
class PluginRegistration(Protocol):
    """Регистрация UI-расширения, которую плагин может удалить при деактивации."""

    def remove(self) -> None:
        """Удалить зарегистрированный элемент из приложения."""


@runtime_checkable
class PluginHost(Protocol):
    """Ограниченный интерфейс главного приложения, доступный плагинам API v1."""

    @property
    def language(self) -> str:
        """Текущий код языка интерфейса."""

    def current_selection(self) -> ObjectSelection | None:
        """Вернуть текущий объект либо `None`, если объект не выбран."""

    def add_tools_action(
        self,
        plugin_id: str,
        action_id: str,
        title: LocalizedText,
        callback: Callable[[], None],
    ) -> PluginRegistration:
        """Добавить локализованную команду в меню «Инструменты»."""

    def show_information(self, title: LocalizedText, message: LocalizedText) -> None:
        """Показать информационное сообщение на текущем языке."""

    def show_status(self, message: LocalizedText, duration_ms: int = 5000) -> None:
        """Временно показать сообщение в строке состояния."""


@runtime_checkable
class Plugin(Protocol):
    """Контракт экземпляра расширения H5 Viewer API v1."""

    plugin_id: str
    display_name: str
    api_version: int

    def activate(self, host: PluginHost) -> None:
        """Зарегистрировать возможности плагина в приложении."""

    def deactivate(self) -> None:
        """Освободить все регистрации и ресурсы плагина."""
