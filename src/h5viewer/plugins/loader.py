"""Изолированная загрузка расширений из Python entry points."""

from __future__ import annotations

from collections.abc import Iterable
from contextlib import suppress
from dataclasses import dataclass
from importlib import metadata
from typing import Protocol, cast

from h5viewer.plugins.api import API_VERSION, ENTRY_POINT_GROUP, Plugin, PluginHost


class _EntryPoint(Protocol):
    """Минимальная часть importlib EntryPoint, нужная загрузчику и тестам."""

    name: str

    def load(self) -> object:
        """Загрузить фабрику расширения."""


@dataclass(frozen=True, slots=True)
class PluginLoadIssue:
    """Ошибка одного расширения, не прерывающая запуск приложения."""

    entry_point: str
    message: str


@dataclass(frozen=True, slots=True)
class PluginLoadReport:
    """Итог обнаружения и активации расширений."""

    loaded_ids: tuple[str, ...]
    issues: tuple[PluginLoadIssue, ...]


class PluginManager:
    """Загружает совместимые плагины и управляет их жизненным циклом."""

    def __init__(self) -> None:
        self._plugins: list[Plugin] = []
        self._issues: list[PluginLoadIssue] = []

    @property
    def loaded_ids(self) -> tuple[str, ...]:
        return tuple(plugin.plugin_id for plugin in self._plugins)

    @property
    def issues(self) -> tuple[PluginLoadIssue, ...]:
        return tuple(self._issues)

    def load(
        self,
        host: PluginHost,
        entry_points: Iterable[_EntryPoint] | None = None,
    ) -> PluginLoadReport:
        """Обнаружить и активировать плагины, сохраняя ошибки в отчёте."""
        if self._plugins:
            raise RuntimeError("Плагины уже загружены")
        self._issues.clear()
        discovered: Iterable[_EntryPoint]
        if entry_points is None:
            discovered = cast(
                Iterable[_EntryPoint],
                metadata.entry_points(group=ENTRY_POINT_GROUP),
            )
        else:
            discovered = entry_points

        known_ids: set[str] = set()
        for entry_point in discovered:
            plugin: Plugin | None = None
            try:
                factory = entry_point.load()
                if not callable(factory):
                    raise TypeError("entry point должен указывать на вызываемую фабрику")
                candidate = factory()
                if not isinstance(candidate, Plugin):
                    raise TypeError("фабрика вернула объект без полного контракта Plugin")
                plugin = candidate
                if plugin.api_version != API_VERSION:
                    raise ValueError(
                        f"несовместимая версия API {plugin.api_version}; нужна {API_VERSION}"
                    )
                if not plugin.plugin_id or plugin.plugin_id in known_ids:
                    raise ValueError(
                        f"некорректный или повторяющийся plugin_id: {plugin.plugin_id!r}"
                    )
                plugin.activate(host)
            except Exception as exc:
                if plugin is not None:
                    with suppress(Exception):
                        plugin.deactivate()
                self._issues.append(PluginLoadIssue(entry_point.name, str(exc)))
                continue
            known_ids.add(plugin.plugin_id)
            self._plugins.append(plugin)
        return PluginLoadReport(self.loaded_ids, self.issues)

    def close(self) -> None:
        """Деактивировать плагины в порядке, обратном загрузке."""
        for plugin in reversed(self._plugins):
            try:
                plugin.deactivate()
            except Exception as exc:
                self._issues.append(PluginLoadIssue(plugin.plugin_id, str(exc)))
        self._plugins.clear()
