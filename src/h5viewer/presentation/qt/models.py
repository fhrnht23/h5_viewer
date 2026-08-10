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
    scalar_to_text,
)
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
    ) -> None:
        """Обновить форму dataset во всех уже загруженных ссылках на объект."""
        root_index = self.index(0, 0)
        pending: list[tuple[TreeNode, QModelIndex]] = [(self._root, root_index)]
        while pending:
            node, index = pending.pop()
            same_object = bool(object_token and node.link.object_token == object_token)
            if node.link.path == path or same_object:
                node.link = replace(node.link, shape=shape)
                shape_index = index.siblingAtColumn(2)
                self.dataChanged.emit(
                    shape_index,
                    shape_index,
                    [int(Qt.ItemDataRole.DisplayRole)],
                )
            for row, child in enumerate(node.children):
                child_index = self.index(row, 0, index)
                pending.append((child, child_index))

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        del parent
        return 5

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
                tr("Tree", "Storage"),
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
