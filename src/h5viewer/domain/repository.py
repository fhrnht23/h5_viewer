"""Порты, реализуемые инфраструктурным слоем HDF5."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from h5viewer.domain.models import (
    AttributeSnapshot,
    DatasetCreationOptions,
    DatasetExtent,
    DatasetPage,
    DatasetSlice,
    LinkRef,
    ObjectDetails,
    ValidationReport,
)


class HdfRepository(Protocol):
    """Операции, необходимые сервисам приложения и моделям Qt."""

    @property
    def path(self) -> Path:
        """Физический файл, к которому обращается репозиторий."""

    def root(self) -> LinkRef:
        """Вернуть ссылку на корневую группу."""

    def child_count(self, group_path: str) -> int:
        """Вернуть количество ссылок в группе."""

    def list_children(self, group_path: str, offset: int, limit: int) -> list[LinkRef]:
        """Вернуть одну страницу ссылок без обхода потомков."""

    def details(self, path: str) -> ObjectDetails:
        """Вернуть ограниченные свойства и сводку всех атрибутов."""

    def read_dataset_page(self, path: str, selection: DatasetSlice) -> DatasetPage:
        """Прочитать ограниченную проекцию набора данных."""

    def read_dataset_value(self, path: str, index: tuple[int, ...]) -> Any:
        """Прочитать ровно один элемент набора данных."""

    def write_dataset_value_raw(self, path: str, index: tuple[int, ...], value: Any) -> None:
        """Восстановить ранее прочитанное значение без разбора строки."""

    def write_dataset_value(self, path: str, index: tuple[int, ...], text: str) -> None:
        """Разобрать и записать ровно один элемент набора данных."""

    def set_attribute(self, path: str, name: str, text: str) -> None:
        """Задать скалярное или совместимое с JSON значение атрибута."""

    def read_attribute_value(self, path: str, name: str) -> AttributeSnapshot:
        """Прочитать полное значение атрибута для отмены."""

    def write_attribute_value_raw(self, path: str, name: str, snapshot: AttributeSnapshot) -> None:
        """Восстановить значение атрибута с сохранением его dtype."""

    def delete_attribute(self, path: str, name: str) -> None:
        """Удалить один атрибут."""

    def create_group(self, parent_path: str, name: str) -> str:
        """Создать группу и вернуть её абсолютный путь."""

    def create_dataset(self, parent_path: str, name: str, options: DatasetCreationOptions) -> str:
        """Создать набор данных и вернуть его абсолютный путь."""

    def dataset_extent(self, path: str) -> DatasetExtent:
        """Вернуть размеры, maxshape и chunks набора данных."""

    def resize_dataset(
        self,
        path: str,
        new_shape: tuple[int, ...],
        *,
        allow_shrink: bool = False,
    ) -> None:
        """Изменить размеры chunked dataset с явным контролем уменьшения."""

    def delete_link(self, path: str) -> None:
        """Удалить одну ссылку из родительской группы."""

    def move_link(self, source_path: str, destination_path: str) -> None:
        """Переименовать или переместить ссылку внутри файла."""

    def flush(self) -> None:
        """Сбросить буферы HDF5."""

    def validate(self) -> ValidationReport:
        """Выполнить структурную проверку с безопасным обходом графа."""
