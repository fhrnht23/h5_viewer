"""Ленивые Qt-модели структуры HDF5 и табличных данных."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, cast

import numpy as np
from PySide6.QtCore import QAbstractItemModel, QAbstractTableModel, QModelIndex, Qt, Signal
from PySide6.QtGui import QColor, QFont

from h5viewer.application.commands import WriteDatasetValueCommand
from h5viewer.application.document import DocumentSession
from h5viewer.domain.errors import H5ViewerError
from h5viewer.domain.models import (
    DatasetPage,
    DatasetSlice,
    LinkKind,
    LinkRef,
    ObjectKind,
    normalize_hdf5_path,
    scalar_to_text,
    split_hdf5_path,
)
from h5viewer.presentation.qt.formatting import format_byte_size
from h5viewer.presentation.qt.icons import interface_icon, object_icon
from h5viewer.presentation.qt.translations import tr


@dataclass(slots=True)
class TreeNode:
    """Узел ленивой UI-модели, представляющий именно ссылку HDF5."""

    link: LinkRef
    parent: TreeNode | None = None
    ancestor_tokens: frozenset[str] = field(default_factory=frozenset)
    children: list[TreeNode] = field(default_factory=list)
    total_children: int | None = None
    cycle: bool = False

    @property
    def row(self) -> int:
        """Вернуть позицию узла среди загруженных соседей."""
        if self.parent is None:
            return 0
        try:
            return self.parent.children.index(self)
        except ValueError:
            return 0


class HdfTreeModel(QAbstractItemModel):
    """Постраничная графо-безопасная модель ссылок одного документа."""

    PathRole = int(Qt.ItemDataRole.UserRole) + 1
    LinkRole = int(Qt.ItemDataRole.UserRole) + 2
    _PAGE_SIZE = 200

    def __init__(self, session: DocumentSession, parent: Any = None) -> None:
        super().__init__(parent)
        self._session = session
        self._root = self._make_root()

    @property
    def session(self) -> DocumentSession:
        return self._session

    def _make_root(self) -> TreeNode:
        link = self._session.repository().root()
        tokens = frozenset({link.object_token}) if link.object_token else frozenset()
        return TreeNode(link, ancestor_tokens=tokens, total_children=link.child_count)

    def refresh(self) -> None:
        """Полностью перечитать корень после изменения активной рабочей копии."""
        self.beginResetModel()
        self._root = self._make_root()
        self.endResetModel()

    def update_dataset_shape(
        self,
        path: str,
        object_token: str | None,
        shape: tuple[int, ...],
        logical_bytes: int | None = None,
        storage_bytes: int | None = None,
    ) -> None:
        """Обновить форму dataset во всех уже загруженных ссылках на объект."""
        root_index = self.index(0, 0)
        pending: list[tuple[TreeNode, QModelIndex]] = [(self._root, root_index)]
        while pending:
            node, index = pending.pop()
            same_object = bool(object_token and node.link.object_token == object_token)
            if node.link.path == path or same_object:
                node.link = replace(
                    node.link,
                    shape=shape,
                    logical_bytes=(
                        node.link.logical_bytes if logical_bytes is None else logical_bytes
                    ),
                    storage_bytes=(
                        node.link.storage_bytes if storage_bytes is None else storage_bytes
                    ),
                )
                shape_index = index.siblingAtColumn(2)
                storage_index = index.siblingAtColumn(5)
                self.dataChanged.emit(
                    shape_index,
                    storage_index,
                    [int(Qt.ItemDataRole.DisplayRole)],
                )
            for row, child in enumerate(node.children):
                child_index = self.index(row, 0, index)
                pending.append((child, child_index))

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        del parent
        return 7

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        if not parent.isValid():
            return 1
        node = self._node(parent)
        return len(node.children)

    def index(self, row: int, column: int, parent: QModelIndex = QModelIndex()) -> QModelIndex:
        if row < 0 or column < 0 or column >= self.columnCount(parent):
            return QModelIndex()
        if not parent.isValid():
            if row != 0:
                return QModelIndex()
            return self.createIndex(0, column, self._root)
        parent_node = self._node(parent)
        if row >= len(parent_node.children):
            return QModelIndex()
        return self.createIndex(row, column, parent_node.children[row])

    def parent(self, child: QModelIndex = QModelIndex()) -> QModelIndex:
        if not child.isValid():
            return QModelIndex()
        node = cast(TreeNode, child.internalPointer())
        if node is self._root:
            return QModelIndex()
        parent_node = node.parent
        if parent_node is None:
            return QModelIndex()
        if parent_node is self._root:
            return self.createIndex(0, 0, self._root)
        return self.createIndex(parent_node.row, 0, parent_node)

    def data(self, index: QModelIndex, role: int = int(Qt.ItemDataRole.DisplayRole)) -> Any:
        if not index.isValid():
            return None
        node = cast(TreeNode, index.internalPointer())
        link = node.link
        if role == int(Qt.ItemDataRole.DisplayRole):
            values = (
                self._display_name(node),
                self._display_type(link),
                self._display_shape(link),
                link.dtype or "",
                format_byte_size(link.logical_bytes),
                format_byte_size(link.storage_bytes),
                link.storage or "",
            )
            return values[index.column()]
        if role == int(Qt.ItemDataRole.ToolTipRole):
            lines = [link.path, f"{tr('Tree', 'Link kind')}: {tr('Type', link.link_kind.value)}"]
            if link.target_path:
                lines.append(f"{tr('Tree', 'Target')}: {link.target_path}")
            if link.external_file:
                lines.append(f"{tr('Tree', 'External file')}: {link.external_file}")
            if link.object_token:
                lines.append(f"{tr('Tree', 'Object token')}: {link.object_token}")
            if link.error:
                lines.append(link.error)
            return "\n".join(lines)
        if role == int(Qt.ItemDataRole.DecorationRole) and index.column() == 0:
            if link.object_kind is ObjectKind.BROKEN_LINK:
                return object_icon("warning")
            if link.link_kind in {LinkKind.SOFT, LinkKind.EXTERNAL}:
                return object_icon("link")
            icon_names = {
                ObjectKind.FILE: "file",
                ObjectKind.GROUP: "folder",
                ObjectKind.DATASET: "dataset",
                ObjectKind.NAMED_DATATYPE: "datatype",
            }
            return object_icon(icon_names.get(link.object_kind, "file"))
        if role == int(Qt.ItemDataRole.ForegroundRole):
            if link.object_kind is ObjectKind.BROKEN_LINK:
                return QColor("#d1495b")
            if node.cycle or link.link_kind in {LinkKind.SOFT, LinkKind.EXTERNAL}:
                return QColor("#8a6d3b")
        if role == int(Qt.ItemDataRole.FontRole) and link.object_kind is ObjectKind.GROUP:
            font = QFont()
            font.setBold(True)
            return font
        if role == self.PathRole:
            return link.path
        if role == self.LinkRole:
            return link
        return None

    def headerData(  # noqa: N802
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = int(Qt.ItemDataRole.DisplayRole),
    ) -> Any:
        if orientation is Qt.Orientation.Horizontal and role == int(Qt.ItemDataRole.DisplayRole):
            return (
                tr("Tree", "Name"),
                tr("Tree", "Type"),
                tr("Tree", "Shape"),
                tr("Tree", "Dtype"),
                tr("Tree", "Logical size"),
                tr("Tree", "On disk"),
                tr("Tree", "Layout"),
            )[section]
        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

    def hasChildren(self, parent: QModelIndex = QModelIndex()) -> bool:  # noqa: N802
        node = self._node(parent)
        if node.cycle or not node.link.can_expand:
            return False
        if node.total_children is not None:
            return node.total_children > 0
        return node.link.object_kind is ObjectKind.GROUP

    def canFetchMore(self, parent: QModelIndex) -> bool:  # noqa: N802
        if not parent.isValid():
            return False
        node = self._node(parent)
        if node.cycle or not node.link.can_expand:
            return False
        if node.total_children is None:
            try:
                node.total_children = self._session.repository().child_count(node.link.path)
            except H5ViewerError:
                node.total_children = 0
        return len(node.children) < node.total_children

    def fetchMore(self, parent: QModelIndex) -> None:  # noqa: N802
        node = self._node(parent)
        if not self.canFetchMore(parent):
            return
        assert node.total_children is not None
        offset = len(node.children)
        count = min(self._PAGE_SIZE, node.total_children - offset)
        try:
            links = self._session.repository().list_children(node.link.path, offset, count)
        except H5ViewerError:
            node.total_children = offset
            return
        if not links:
            node.total_children = offset
            return
        self.beginInsertRows(parent, offset, offset + len(links) - 1)
        for link in links:
            cycle = bool(link.object_token and link.object_token in node.ancestor_tokens)
            tokens = node.ancestor_tokens
            if link.object_token:
                tokens = tokens | {link.object_token}
            node.children.append(
                TreeNode(
                    link=link,
                    parent=node,
                    ancestor_tokens=frozenset(tokens),
                    total_children=link.child_count,
                    cycle=cycle,
                )
            )
        self.endInsertRows()

    def _node(self, index: QModelIndex) -> TreeNode:
        return cast(TreeNode, index.internalPointer()) if index.isValid() else self._root

    @staticmethod
    def _display_name(node: TreeNode) -> str:
        if node.cycle:
            return f"{node.link.name} ↻"
        if node.link.link_kind is LinkKind.SOFT:
            return f"{node.link.name} →"
        if node.link.link_kind is LinkKind.EXTERNAL:
            return f"{node.link.name} ⇥"
        return node.link.name

    @staticmethod
    def _display_type(link: LinkRef) -> str:
        object_text = tr("Type", link.object_kind.value)
        if link.link_kind in {LinkKind.ROOT, LinkKind.HARD}:
            return object_text
        return f"{object_text} · {tr('Type', link.link_kind.value)}"

    @staticmethod
    def _display_shape(link: LinkRef) -> str:
        if link.object_kind is not ObjectKind.DATASET:
            return ""
        return "NULL" if link.shape is None else str(link.shape)


class HdfFolderModel(QAbstractTableModel):
    """Постраничная плоская модель содержимого одной HDF5-группы."""

    PathRole = HdfTreeModel.PathRole
    LinkRole = HdfTreeModel.LinkRole
    ParentRole = HdfTreeModel.LinkRole + 1
    _PAGE_SIZE = 200

    def __init__(
        self,
        session: DocumentSession,
        group_path: str = "/",
        parent: Any = None,
    ) -> None:
        super().__init__(parent)
        self._session = session
        self._group_path = "/"
        self._links: list[LinkRef] = []
        self._total_children = 0
        self.set_group(group_path)

    @property
    def group_path(self) -> str:
        """Вернуть путь отображаемой группы."""
        return self._group_path

    @property
    def _link_row_offset(self) -> int:
        """Оставить нулевую строку для перехода к родителю вне корня."""
        return int(self._group_path != "/")

    @property
    def parent_path(self) -> str:
        """Вернуть путь родительской группы для служебной строки."""
        parent, _name = split_hdf5_path(self._group_path)
        return parent

    def set_group(self, path: str) -> None:
        """Перейти в группу и загрузить первую ограниченную страницу ссылок."""
        normalized = normalize_hdf5_path(path)
        repository = self._session.repository()
        total = repository.child_count(normalized)
        links = repository.list_children(normalized, 0, min(self._PAGE_SIZE, total))
        self.beginResetModel()
        self._group_path = normalized
        self._links = links
        self._total_children = total
        self.endResetModel()

    def refresh(self) -> None:
        """Повторно прочитать текущую группу после изменения документа."""
        self.set_group(self._group_path)

    def update_dataset_shape(
        self,
        path: str,
        object_token: str | None,
        shape: tuple[int, ...],
        logical_bytes: int | None = None,
        storage_bytes: int | None = None,
    ) -> None:
        """Обновить форму dataset в загруженных строках текущей группы."""
        for link_row, link in enumerate(self._links):
            same_object = bool(object_token and link.object_token == object_token)
            if link.path != path and not same_object:
                continue
            self._links[link_row] = replace(
                link,
                shape=shape,
                logical_bytes=link.logical_bytes if logical_bytes is None else logical_bytes,
                storage_bytes=link.storage_bytes if storage_bytes is None else storage_bytes,
            )
            shape_index = self.index(link_row + self._link_row_offset, 2)
            storage_index = self.index(link_row + self._link_row_offset, 5)
            self.dataChanged.emit(
                shape_index,
                storage_index,
                [int(Qt.ItemDataRole.DisplayRole)],
            )

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        del parent
        return 7

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._links) + self._link_row_offset

    def data(self, index: QModelIndex, role: int = int(Qt.ItemDataRole.DisplayRole)) -> Any:
        if not index.isValid() or index.row() >= self.rowCount():
            return None
        if self._link_row_offset and index.row() == 0:
            if role == int(Qt.ItemDataRole.DisplayRole):
                return ".." if index.column() == 0 else ""
            if role == int(Qt.ItemDataRole.ToolTipRole):
                return tr("Tree", "Parent group")
            if role == int(Qt.ItemDataRole.DecorationRole) and index.column() == 0:
                return interface_icon("up")
            if role == int(Qt.ItemDataRole.FontRole):
                font = QFont()
                font.setBold(True)
                return font
            if role == self.PathRole:
                return self.parent_path
            if role == self.ParentRole:
                return True
            return None
        link = self._links[index.row() - self._link_row_offset]
        if role == int(Qt.ItemDataRole.DisplayRole):
            values = (
                HdfTreeModel._display_name(TreeNode(link)),
                HdfTreeModel._display_type(link),
                HdfTreeModel._display_shape(link),
                link.dtype or "",
                format_byte_size(link.logical_bytes),
                format_byte_size(link.storage_bytes),
                link.storage or "",
            )
            return values[index.column()]
        if role == int(Qt.ItemDataRole.ToolTipRole):
            lines = [link.path, f"{tr('Tree', 'Link kind')}: {tr('Type', link.link_kind.value)}"]
            if link.target_path:
                lines.append(f"{tr('Tree', 'Target')}: {link.target_path}")
            if link.external_file:
                lines.append(f"{tr('Tree', 'External file')}: {link.external_file}")
            if link.object_token:
                lines.append(f"{tr('Tree', 'Object token')}: {link.object_token}")
            if link.error:
                lines.append(link.error)
            return "\n".join(lines)
        if role == int(Qt.ItemDataRole.DecorationRole) and index.column() == 0:
            if link.object_kind is ObjectKind.BROKEN_LINK:
                return object_icon("warning")
            if link.link_kind in {LinkKind.SOFT, LinkKind.EXTERNAL}:
                return object_icon("link")
            icon_names = {
                ObjectKind.GROUP: "folder",
                ObjectKind.DATASET: "dataset",
                ObjectKind.NAMED_DATATYPE: "datatype",
            }
            return object_icon(icon_names.get(link.object_kind, "file"))
        if role == int(Qt.ItemDataRole.ForegroundRole):
            if link.object_kind is ObjectKind.BROKEN_LINK:
                return QColor("#d1495b")
            if link.link_kind in {LinkKind.SOFT, LinkKind.EXTERNAL}:
                return QColor("#8a6d3b")
        if role == int(Qt.ItemDataRole.FontRole) and link.object_kind is ObjectKind.GROUP:
            font = QFont()
            font.setBold(True)
            return font
        if role == self.PathRole:
            return link.path
        if role == self.LinkRole:
            return link
        if role == self.ParentRole:
            return False
        return None

    def headerData(  # noqa: N802
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = int(Qt.ItemDataRole.DisplayRole),
    ) -> Any:
        if orientation is Qt.Orientation.Horizontal and role == int(Qt.ItemDataRole.DisplayRole):
            return (
                tr("Tree", "Name"),
                tr("Tree", "Type"),
                tr("Tree", "Shape"),
                tr("Tree", "Dtype"),
                tr("Tree", "Logical size"),
                tr("Tree", "On disk"),
                tr("Tree", "Layout"),
            )[section]
        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

    def canFetchMore(self, parent: QModelIndex = QModelIndex()) -> bool:  # noqa: N802
        return not parent.isValid() and len(self._links) < self._total_children

    def fetchMore(self, parent: QModelIndex = QModelIndex()) -> None:  # noqa: N802
        if not self.canFetchMore(parent):
            return
        offset = len(self._links)
        count = min(self._PAGE_SIZE, self._total_children - offset)
        try:
            links = self._session.repository().list_children(self._group_path, offset, count)
        except H5ViewerError:
            self._total_children = offset
            return
        if not links:
            self._total_children = offset
            return
        first_row = offset + self._link_row_offset
        self.beginInsertRows(QModelIndex(), first_row, first_row + len(links) - 1)
        self._links.extend(links)
        self.endInsertRows()


class DatasetTableModel(QAbstractTableModel):
    """Ограниченная страничная модель двумерной проекции dataset."""

    edit_failed = Signal(str)
    content_changed = Signal()

    def __init__(self, parent: Any = None) -> None:
        super().__init__(parent)
        self._session: DocumentSession | None = None
        self._path: str | None = None
        self._selection: DatasetSlice | None = None
        self._page: DatasetPage | None = None
        self._error: str | None = None

    @property
    def error(self) -> str | None:
        return self._error

    @property
    def page(self) -> DatasetPage | None:
        return self._page

    def clear(self) -> None:
        self.beginResetModel()
        self._session = None
        self._path = None
        self._selection = None
        self._page = None
        self._error = None
        self.endResetModel()

    def load(self, session: DocumentSession, path: str, selection: DatasetSlice) -> None:
        """Синхронно загрузить только заданную ограниченную страницу."""
        self.beginResetModel()
        self._session = session
        self._path = path
        self._selection = selection
        self._error = None
        try:
            self._page = session.repository().read_dataset_page(path, selection)
        except H5ViewerError as exc:
            self._page = None
            self._error = str(exc)
        self.endResetModel()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        if parent.isValid() or self._page is None:
            return 0
        return int(self._page.values.shape[0])

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        if parent.isValid() or self._page is None:
            return 0
        return int(self._page.values.shape[1])

    def data(self, index: QModelIndex, role: int = int(Qt.ItemDataRole.DisplayRole)) -> Any:
        if not index.isValid() or self._page is None:
            return None
        value = self._page.values[index.row(), index.column()]
        if role in {int(Qt.ItemDataRole.DisplayRole), int(Qt.ItemDataRole.EditRole)}:
            return _cell_text(value)
        if role == int(Qt.ItemDataRole.TextAlignmentRole) and isinstance(
            value, (int, float, complex, np.number)
        ):
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if role == int(Qt.ItemDataRole.ToolTipRole):
            return f"dtype: {self._page.dtype}\n{_cell_text(value)}"
        return None

    def setData(  # noqa: N802
        self,
        index: QModelIndex,
        value: Any,
        role: int = int(Qt.ItemDataRole.EditRole),
    ) -> bool:
        if (
            role != int(Qt.ItemDataRole.EditRole)
            or not index.isValid()
            or self._session is None
            or self._path is None
            or self._selection is None
            or self._page is None
            or not self._page.editable
            or not self._session.is_editing
        ):
            return False
        element_index = self._element_index(index.row(), index.column())
        try:
            self._session.execute(WriteDatasetValueCommand(self._path, element_index, str(value)))
            self._page = self._session.repository().read_dataset_page(self._path, self._selection)
        except H5ViewerError as exc:
            self.edit_failed.emit(str(exc))
            return False
        self.dataChanged.emit(index, index)
        self.content_changed.emit()
        return True

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if (
            index.isValid()
            and self._session is not None
            and self._session.is_editing
            and self._page is not None
            and self._page.editable
        ):
            flags |= Qt.ItemFlag.ItemIsEditable
        return flags

    def headerData(  # noqa: N802
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = int(Qt.ItemDataRole.DisplayRole),
    ) -> Any:
        if role != int(Qt.ItemDataRole.DisplayRole) or self._page is None:
            return None
        if orientation is Qt.Orientation.Horizontal:
            return str(self._page.column_offset + section)
        return str(self._page.row_offset + section)

    def _element_index(self, row: int, column: int) -> tuple[int, ...]:
        assert self._selection is not None
        indices = list(self._selection.fixed_indices)
        if self._selection.row_axis is not None:
            indices[self._selection.row_axis] = self._selection.row_offset + row
        if self._selection.column_axis is not None:
            indices[self._selection.column_axis] = self._selection.column_offset + column
        return tuple(indices)


def _cell_text(value: Any) -> str:
    """Преобразовать одно значение таблицы без неявной потери информации."""
    if isinstance(value, np.void):
        return repr(value.tolist())
    if isinstance(value, np.ndarray):
        return np.array2string(value, threshold=24, edgeitems=3)
    return scalar_to_text(value)
