"""Одна навигационная панель в стиле файлового менеджера."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QSortFilterProxyModel, Qt, Signal
from PySide6.QtGui import QAction, QStandardItemModel
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QInputDialog,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from h5viewer.application.commands import (
    CreateDatasetCommand,
    CreateGroupCommand,
    MoveLinkCommand,
)
from h5viewer.application.document import DocumentSession
from h5viewer.domain.errors import H5ViewerError
from h5viewer.domain.models import LinkRef, ObjectKind, split_hdf5_path
from h5viewer.presentation.qt.dialogs import DatasetCreationDialog
from h5viewer.presentation.qt.models import HdfTreeModel
from h5viewer.presentation.qt.translations import tr


class BrowserPane(QWidget):
    """Независимая панель выбора документа и навигации по его графу."""

    object_selected = Signal(object, object)
    status_message = Signal(str)
    document_changed = Signal(object)
    content_changed = Signal(object)

    def __init__(
        self,
        ensure_editing: Callable[[DocumentSession], bool],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._ensure_editing = ensure_editing
        self._documents: list[DocumentSession] = []
        self._session: DocumentSession | None = None
        self._model: HdfTreeModel | None = None
        self._proxy = QSortFilterProxyModel(self)
        self._empty_model = QStandardItemModel(self)
        self._proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._proxy.setRecursiveFilteringEnabled(True)
        self._proxy.setFilterKeyColumn(-1)
        self._create_ui()
        self.retranslate_ui()

    @property
    def session(self) -> DocumentSession | None:
        return self._session

    def _create_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(5)

        self.document_combo = QComboBox(self)
        self.document_combo.currentIndexChanged.connect(self._select_document_index)
        layout.addWidget(self.document_combo)

        path_row = QHBoxLayout()
        self.path_edit = QLineEdit("/", self)
        self.path_edit.setReadOnly(True)
        self.root_button = QPushButton("/", self)
        self.root_button.setFixedWidth(34)
        self.root_button.clicked.connect(self._select_root)
        path_row.addWidget(self.root_button)
        path_row.addWidget(self.path_edit, 1)
        layout.addLayout(path_row)

        self.filter_edit = QLineEdit(self)
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.textChanged.connect(self._proxy.setFilterFixedString)
        layout.addWidget(self.filter_edit)

        self.tree = QTreeView(self)
        self.tree.setAlternatingRowColors(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setSelectionBehavior(QTreeView.SelectionBehavior.SelectRows)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._show_context_menu)
        self.tree.clicked.connect(self._tree_clicked)
        self.tree.doubleClicked.connect(self._tree_double_clicked)
        self.tree.setModel(self._proxy)
        layout.addWidget(self.tree, 1)

    def retranslate_ui(self) -> None:
        """Обновить локализуемые подписи панели."""
        self.filter_edit.setPlaceholderText(tr("Pane", "Filter objects…"))
        if self._model is not None:
            self._model.headerDataChanged.emit(Qt.Orientation.Horizontal, 0, 4)

    def set_documents(
        self,
        documents: list[DocumentSession],
        preferred: DocumentSession | None = None,
    ) -> None:
        """Обновить общий список документов, сохранив выбранный при возможности."""
        current = preferred or self._session
        self._documents = documents
        self.document_combo.blockSignals(True)
        self.document_combo.clear()
        for document in documents:
            self.document_combo.addItem(document.original_path.name, document)
            index = self.document_combo.count() - 1
            self.document_combo.setItemData(
                index, str(document.original_path), Qt.ItemDataRole.ToolTipRole
            )
        selected_index = (
            documents.index(current) if current in documents else (0 if documents else -1)
        )
        self.document_combo.setCurrentIndex(selected_index)
        self.document_combo.blockSignals(False)
        self._select_document_index(selected_index)

    def select_document(self, session: DocumentSession) -> None:
        """Показать указанный уже открытый документ."""
        if session not in self._documents:
            return
        self.document_combo.setCurrentIndex(self._documents.index(session))

    def refresh(self) -> None:
        """Перечитать активную структуру после команды или сохранения."""
        if self._model is None:
            return
        try:
            self._model.refresh()
            self.tree.expandToDepth(0)
            self._select_root()
        except H5ViewerError as exc:
            self.status_message.emit(str(exc))

    def current_link(self) -> LinkRef | None:
        """Вернуть выбранную ссылку исходной модели."""
        index = self.tree.currentIndex()
        if not index.isValid() or self._model is None:
            return None
        source = self._proxy.mapToSource(index.siblingAtColumn(0))
        value = self._model.data(source, HdfTreeModel.LinkRole)
        return value if isinstance(value, LinkRef) else None

    def update_dataset_shape(
        self,
        session: DocumentSession,
        path: str,
        object_token: str | None,
        shape: tuple[int, ...],
    ) -> None:
        """Обновить форму dataset без сброса раскрытия дерева и выбора."""
        if self._session is session and self._model is not None:
            self._model.update_dataset_shape(path, object_token, shape)

    def _select_document_index(self, index: int) -> None:
        if index < 0 or index >= len(self._documents):
            self._session = None
            self._model = None
            self._proxy.setSourceModel(self._empty_model)
            self.path_edit.setText("")
            return
        self._session = self._documents[index]
        try:
            self._model = HdfTreeModel(self._session, self)
        except H5ViewerError as exc:
            QMessageBox.critical(self, tr("Dialog", "Error"), str(exc))
            return
        self._proxy.setSourceModel(self._model)
        self.tree.expandToDepth(0)
        self.document_changed.emit(self._session)
        self._select_root()

    def _select_root(self) -> None:
        if self._session is None:
            return
        self.path_edit.setText("/")
        try:
            root = self._session.repository().root()
        except H5ViewerError as exc:
            self.status_message.emit(str(exc))
            return
        self.object_selected.emit(self._session, root)

    def _tree_clicked(self, proxy_index: Any) -> None:
        if self._model is None or self._session is None:
            return
        source = self._proxy.mapToSource(proxy_index.siblingAtColumn(0))
        link = self._model.data(source, HdfTreeModel.LinkRole)
        if isinstance(link, LinkRef):
            self.path_edit.setText(link.path)
            self.object_selected.emit(self._session, link)

    def _tree_double_clicked(self, proxy_index: Any) -> None:
        if not proxy_index.isValid():
            return
        if self.tree.isExpanded(proxy_index):
            self.tree.collapse(proxy_index)
        else:
            self.tree.expand(proxy_index)

    def _show_context_menu(self, position: Any) -> None:
        if self._session is None:
            return
        link = self.current_link()
        menu = QMenu(self)
        create_group = QAction(tr("Pane", "Create group…"), menu)
        create_group.triggered.connect(lambda: self._create_group(link))
        menu.addAction(create_group)
        create_dataset = QAction(tr("Pane", "Create dataset…"), menu)
        create_dataset.triggered.connect(lambda: self._create_dataset(link))
        menu.addAction(create_dataset)
        menu.addSeparator()
        rename = QAction(tr("Pane", "Rename…"), menu)
        rename.setEnabled(link is not None and link.path != "/")
        rename.triggered.connect(lambda: self._rename_link(link))
        menu.addAction(rename)
        menu.exec(self.tree.viewport().mapToGlobal(position))

    def _create_group(self, selected: LinkRef | None) -> None:
        if self._session is None or not self._ensure_editing(self._session):
            return
        parent_path = self._target_group(selected)
        name, accepted = QInputDialog.getText(
            self,
            tr("Pane", "Create group"),
            tr("Pane", "Group name"),
        )
        if not accepted or not name:
            return
        try:
            self._session.execute(CreateGroupCommand(parent_path, name))
        except H5ViewerError as exc:
            QMessageBox.critical(self, tr("Dialog", "Error"), str(exc))
            return
        self.refresh()
        self.content_changed.emit(self._session)

    def _create_dataset(self, selected: LinkRef | None) -> None:
        """Создать dataset в выбранной или родительской группе."""
        if self._session is None:
            return
        parent_path = self._target_group(selected)
        dialog = DatasetCreationDialog(parent_path, self)
        if dialog.exec() != DatasetCreationDialog.DialogCode.Accepted:
            return
        if not self._ensure_editing(self._session):
            return
        request = dialog.request()
        try:
            self._session.execute(CreateDatasetCommand(parent_path, request.name, request.options))
        except H5ViewerError as exc:
            QMessageBox.critical(self, tr("Dialog", "Error"), str(exc))
            return
        self.refresh()
        self.content_changed.emit(self._session)

    @staticmethod
    def _target_group(selected: LinkRef | None) -> str:
        """Выбрать группу назначения по текущему объекту панели."""
        if selected is None:
            return "/"
        return selected.path if selected.object_kind is ObjectKind.GROUP else selected.parent_path

    def _rename_link(self, selected: LinkRef | None) -> None:
        if (
            self._session is None
            or selected is None
            or selected.path == "/"
            or not self._ensure_editing(self._session)
        ):
            return
        parent_path, old_name = split_hdf5_path(selected.path)
        name, accepted = QInputDialog.getText(
            self,
            tr("Pane", "Rename object"),
            tr("Pane", "New name"),
            text=old_name,
        )
        if not accepted or not name or name == old_name:
            return
        destination = f"/{name}" if parent_path == "/" else f"{parent_path}/{name}"
        try:
            self._session.execute(MoveLinkCommand(selected.path, destination))
        except H5ViewerError as exc:
            QMessageBox.critical(self, tr("Dialog", "Error"), str(exc))
            return
        self.refresh()
        self.content_changed.emit(self._session)
