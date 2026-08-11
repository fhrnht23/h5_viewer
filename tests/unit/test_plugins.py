"""Тесты версионированного API и изолированной загрузки расширений."""

from __future__ import annotations

from dataclasses import dataclass

from h5viewer.plugins import API_VERSION, LocalizedText, PluginHost
from h5viewer.plugins.loader import PluginManager


class _Registration:
    def __init__(self) -> None:
        self.removed = False

    def remove(self) -> None:
        self.removed = True


class _Host:
    language = "ru"

    def current_selection(self) -> None:
        return None

    def add_tools_action(self, *_args: object) -> _Registration:
        return _Registration()

    def show_information(self, *_args: object) -> None:
        return None

    def show_status(self, *_args: object, **_kwargs: object) -> None:
        return None


class _Plugin:
    display_name = "Тестовый плагин"

    def __init__(self, plugin_id: str, api_version: int = API_VERSION) -> None:
        self.plugin_id = plugin_id
        self.api_version = api_version
        self.activated = False
        self.deactivated = False

    def activate(self, host: PluginHost) -> None:
        del host
        self.activated = True

    def deactivate(self) -> None:
        self.deactivated = True


@dataclass
class _EntryPoint:
    name: str
    factory: object

    def load(self) -> object:
        return self.factory


def test_localized_text_uses_russian_only_for_russian_locale() -> None:
    text = LocalizedText("Русский", "English")

    assert text.resolve("ru") == "Русский"
    assert text.resolve("ru_RU") == "Русский"
    assert text.resolve("en") == "English"


def test_plugin_manager_isolates_incompatible_and_duplicate_plugins() -> None:
    first = _Plugin("org.example.first")
    incompatible = _Plugin("org.example.future", API_VERSION + 1)
    duplicate = _Plugin("org.example.first")
    manager = PluginManager()

    report = manager.load(
        _Host(),
        (
            _EntryPoint("first", lambda: first),
            _EntryPoint("future", lambda: incompatible),
            _EntryPoint("duplicate", lambda: duplicate),
        ),
    )

    assert report.loaded_ids == ("org.example.first",)
    assert len(report.issues) == 2
    assert first.activated
    assert incompatible.deactivated
    assert duplicate.deactivated

    manager.close()
    assert first.deactivated
    assert manager.loaded_ids == ()
