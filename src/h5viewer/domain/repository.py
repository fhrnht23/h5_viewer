"""Порты, реализуемые инфраструктурным слоем HDF5."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from h5viewer.domain.models import (
    AttributeSnapshot,
    DatasetCreationOptions,
    DatasetExtent,
    DatasetPage,
    DatasetShrinkSnapshot,
    DatasetSlice,
    DeletedLinkSnapshot,
    LinkCreationOptions,
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

    def link(self, path: str) -> LinkRef:
        """Вернуть описание одной именованной ссылки по абсолютному пути."""

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

    def shrink_dataset_with_snapshot(
        self,
        path: str,
        new_shape: tuple[int, ...],
    ) -> DatasetShrinkSnapshot:
        """Уменьшить dataset после создания полного дискового снимка файла."""

    def restore_dataset_shrink_snapshot(self, snapshot: DatasetShrinkSnapshot) -> None:
        """Атомарно восстановить рабочий файл из снимка уменьшения."""

    def create_link(
        self,
        parent_path: str,
        name: str,
        options: LinkCreationOptions,
    ) -> str:
        """Создать hard, soft или external link и вернуть её путь."""

    def delete_link_with_snapshot(self, path: str) -> DeletedLinkSnapshot:
        """Удалить ссылку, подготовив дисковый snapshot при необходимости."""

    def restore_deleted_link(self, path: str, snapshot: DeletedLinkSnapshot) -> None:
        """Точно восстановить ранее удалённую ссылку."""

    def delete_link(self, path: str) -> None:
        """Удалить одну ссылку из родительской группы."""

    def move_link(self, source_path: str, destination_path: str) -> None:
        """Переименовать или переместить ссылку внутри файла."""

    def flush(self) -> None:
        """Сбросить буферы HDF5."""

    def validate(self) -> ValidationReport:
        """Выполнить структурную проверку с безопасным обходом графа."""
