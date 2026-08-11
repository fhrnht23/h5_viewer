"""Одна навигационная панель в стиле файлового менеджера."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QEvent, QModelIndex, QObject, QSortFilterProxyModel, Qt, Signal
from PySide6.QtGui import QAction, QKeyEvent, QKeySequence, QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QToolButton,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from h5viewer.application.commands import (
    CreateDatasetCommand,
    CreateGroupCommand,
    CreateLinkCommand,
    DeleteLinkCommand,
    MoveLinkCommand,
)
from h5viewer.application.document import DocumentSession
from h5viewer.domain.errors import H5ViewerError
from h5viewer.domain.models import LinkRef, ObjectKind, split_hdf5_path
from h5viewer.presentation.qt.dialogs import DatasetCreationDialog, LinkCreationDialog
from h5viewer.presentation.qt.icons import interface_icon, object_icon
from h5viewer.presentation.qt.models import HdfFolderModel, HdfTreeModel
from h5viewer.presentation.qt.translations import tr


class ObjectTreeView(QTreeView):
    """Представление структуры, резервирующее Enter для активации объекта."""

    open_requested = Signal()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() in {Qt.Key.Key_Return, Qt.Key.Key_Enter}:
            self.open_requested.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class BrowserPane(QWidget):
    """Независимая панель выбора документа и навигации по его графу."""

    object_selected = Signal(object, object)
    object_open_requested = Signal(object, object)
    status_message = Signal(str)
    document_changed = Signal(object)
    content_changed = Signal(object)
    activated = Signal(object)

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
        self._folder_model: HdfFolderModel | None = None
        self._navigation_mode = "tree"
        self._proxy = QSortFilterProxyModel(self)
        self._empty_model = QStandardItemModel(self)
        self._proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._proxy.setRecursiveFilteringEnabled(True)
        self._proxy.setFilterKeyColumn(-1)
        self.setObjectName("browserPane")
        self.setProperty("activePane", False)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._create_ui()
        self.retranslate_ui()

    @property
    def session(self) -> DocumentSession | None:
        return self._session

    @property
    def navigation_mode(self) -> str:
        """Вернуть активный режим навигации: дерево или папки."""
        return self._navigation_mode

    def _create_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        self.document_combo = QComboBox(self)
        self.document_combo.setObjectName("documentCombo")
        self.document_combo.currentIndexChanged.connect(self._select_document_index)
        layout.addWidget(self.document_combo)

        path_row = QHBoxLayout()
        path_row.setSpacing(6)
        self.path_edit = QLineEdit("/", self)
        self.path_edit.setObjectName("pathEdit")
        self.path_edit.setReadOnly(True)
        self.root_button = QPushButton("/", self)
        self.root_button.setObjectName("rootButton")
        self.root_button.setFixedWidth(36)
        self.root_button.clicked.connect(self._select_root)
        self.up_button = QToolButton(self)
        self.up_button.setObjectName("paneNavigationButton")
        self.up_button.setIcon(interface_icon("up"))
        self.up_button.setFixedSize(34, 34)
        self.up_button.setVisible(False)
        self.up_button.clicked.connect(self._go_up)
        path_row.addWidget(self.root_button)
        path_row.addWidget(self.up_button)
        path_row.addWidget(self.path_edit, 1)

        self.tree_mode_button = QToolButton(self)
        self.tree_mode_button.setObjectName("paneNavigationButton")
        self.tree_mode_button.setIcon(interface_icon("tree"))
        self.tree_mode_button.setCheckable(True)
        self.tree_mode_button.setChecked(True)
        self.tree_mode_button.setFixedSize(34, 34)
        self.tree_mode_button.clicked.connect(lambda: self.set_navigation_mode("tree"))
        self.folder_mode_button = QToolButton(self)
        self.folder_mode_button.setObjectName("paneNavigationButton")
        self.folder_mode_button.setIcon(interface_icon("folder"))
        self.folder_mode_button.setCheckable(True)
        self.folder_mode_button.setFixedSize(34, 34)
        self.folder_mode_button.clicked.connect(lambda: self.set_navigation_mode("folders"))
        self.navigation_mode_group = QButtonGroup(self)
        self.navigation_mode_group.setExclusive(True)
        self.navigation_mode_group.addButton(self.tree_mode_button)
        self.navigation_mode_group.addButton(self.folder_mode_button)
        path_row.addWidget(self.tree_mode_button)
        path_row.addWidget(self.folder_mode_button)
        layout.addLayout(path_row)

        self.filter_edit = QLineEdit(self)
        self.filter_edit.setObjectName("filterEdit")
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_icon_action = self.filter_edit.addAction(
            interface_icon("search"),
            QLineEdit.ActionPosition.LeadingPosition,
        )
        self.filter_edit.textChanged.connect(self._proxy.setFilterFixedString)
        layout.addWidget(self.filter_edit)

        self.tree = ObjectTreeView(self)
        self.tree.setObjectName("objectTree")
        self.tree.setAlternatingRowColors(False)
        self.tree.setUniformRowHeights(True)
        self.tree.setSelectionBehavior(QTreeView.SelectionBehavior.SelectRows)
        self.tree.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.tree.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.tree.setIndentation(20)
        self.tree.setAnimated(True)
        self.tree.setAllColumnsShowFocus(True)
        header = self.tree.header()
        header.setMinimumSectionSize(74)
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(True)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._show_context_menu)
        self.tree.clicked.connect(self._tree_clicked)
        self.tree.doubleClicked.connect(self._tree_double_clicked)
        self.tree.open_requested.connect(self._activate_current_link)
        self.tree.setModel(self._proxy)
        layout.addWidget(self.tree, 1)

        # Любой ввод внутри карточки делает её активной панелью файлового менеджера.
        for widget in (
            self.document_combo,
            self.root_button,
            self.up_button,
            self.path_edit,
            self.tree_mode_button,
            self.folder_mode_button,
            self.filter_edit,
            self.tree,
            self.tree.viewport(),
        ):
            widget.installEventFilter(self)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        """Сообщить главному окну о фокусе или щелчке внутри панели."""
        if event.type() in {QEvent.Type.FocusIn, QEvent.Type.MouseButtonPress}:
            self.activated.emit(self)
        return super().eventFilter(watched, event)

    def retranslate_ui(self) -> None:
        """Обновить локализуемые подписи панели."""
        self.filter_edit.setPlaceholderText(tr("Pane", "Filter objects…"))
        self.root_button.setToolTip(tr("Pane", "Go to root group"))
        self.up_button.setToolTip(tr("Pane", "Go to parent group"))
        self.tree_mode_button.setToolTip(tr("Pane", "Tree view"))
        self.tree_mode_button.setAccessibleName(tr("Pane", "Tree view"))
        self.folder_mode_button.setToolTip(tr("Pane", "Folder view"))
        self.folder_mode_button.setAccessibleName(tr("Pane", "Folder view"))
        if self._model is not None:
            self._model.headerDataChanged.emit(Qt.Orientation.Horizontal, 0, 4)
        if self._folder_model is not None:
            self._folder_model.headerDataChanged.emit(Qt.Orientation.Horizontal, 0, 4)

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
            self.document_combo.addItem(
                object_icon("file"),
                document.original_path.name,
                document,
            )
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

    def refresh_visuals(self) -> None:
        """Обновить значки после смены светлой или тёмной темы."""
        for index in range(self.document_combo.count()):
            self.document_combo.setItemIcon(index, object_icon("file"))
        self.filter_icon_action.setIcon(interface_icon("search"))
        self.up_button.setIcon(interface_icon("up"))
        self.tree_mode_button.setIcon(interface_icon("tree"))
        self.folder_mode_button.setIcon(interface_icon("folder"))
        self.tree.viewport().update()

    def select_document(self, session: DocumentSession) -> None:
        """Показать указанный уже открытый документ."""
        if session not in self._documents:
            return
        self.document_combo.setCurrentIndex(self._documents.index(session))

    def refresh(self) -> None:
        """Перечитать активную структуру после команды или сохранения."""
        if self._model is None or self._folder_model is None:
            return
        try:
            self._model.refresh()
            if self._navigation_mode == "folders":
                group_path = self._refresh_folder_with_fallback()
                self.path_edit.setText(group_path)
                self.up_button.setEnabled(group_path != "/")
                assert self._session is not None
                group = self._session.repository().link(group_path)
                self.object_selected.emit(self._session, group)
            else:
                self.tree.expandToDepth(0)
                self._select_root()
        except H5ViewerError as exc:
            self.status_message.emit(str(exc))

    def current_link(self) -> LinkRef | None:
        """Вернуть выбранную ссылку исходной модели."""
        index = self.tree.currentIndex()
        if not index.isValid() or self._proxy.sourceModel() is None:
            return None
        source = self._proxy.mapToSource(index.siblingAtColumn(0))
        value = self._proxy.sourceModel().data(source, HdfTreeModel.LinkRole)
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
            if self._folder_model is not None:
                self._folder_model.update_dataset_shape(path, object_token, shape)

    def _select_document_index(self, index: int) -> None:
        if index < 0 or index >= len(self._documents):
            self._session = None
            self._model = None
            self._folder_model = None
            self._proxy.setSourceModel(self._empty_model)
            self.path_edit.setText("")
            self.up_button.setEnabled(False)
            return
        self._session = self._documents[index]
        try:
            self._model = HdfTreeModel(self._session, self)
            self._folder_model = HdfFolderModel(self._session, "/", self)
        except H5ViewerError as exc:
            QMessageBox.critical(self, tr("Dialog", "Error"), str(exc))
            return
        self._apply_navigation_model()
        self._resize_tree_columns()
        self.document_changed.emit(self._session)
        self._select_root()

    def _resize_tree_columns(self) -> None:
        """Выделить больше места пути объекта после подключения модели."""
        header = self.tree.header()
        header.resizeSection(0, 220)
        header.resizeSection(1, 95)
        header.resizeSection(2, 85)
        header.resizeSection(3, 105)

    def set_navigation_mode(self, mode: str) -> None:
        """Переключить панель между деревом и содержимым одной группы."""
        if mode not in {"tree", "folders"}:
            raise ValueError(f"Unknown navigation mode: {mode}")
        if mode == self._navigation_mode:
            return
        selected = self.current_link()
        self._navigation_mode = mode
        self.tree_mode_button.setChecked(mode == "tree")
        self.folder_mode_button.setChecked(mode == "folders")
        if self._session is None or self._model is None or self._folder_model is None:
            self._apply_navigation_model()
            return
        if mode == "folders":
            group_path = "/"
            if selected is not None:
                group_path = selected.path if selected.can_expand else selected.parent_path
            try:
                self._folder_model.set_group(group_path)
            except H5ViewerError as exc:
                self.status_message.emit(str(exc))
                self._folder_model.set_group("/")
            self._apply_navigation_model()
            self._select_folder_group()
            return
        self._apply_navigation_model()
        self._select_root()

    def _apply_navigation_model(self) -> None:
        """Подключить к представлению модель выбранного режима."""
        is_folder_mode = self._navigation_mode == "folders"
        source_model = self._folder_model if is_folder_mode else self._model
        self._proxy.setRecursiveFilteringEnabled(not is_folder_mode)
        self._proxy.setSourceModel(source_model or self._empty_model)
        self.tree.setRootIsDecorated(not is_folder_mode)
        self.tree.setItemsExpandable(not is_folder_mode)
        self.tree.setIndentation(0 if is_folder_mode else 20)
        self.up_button.setVisible(is_folder_mode)
        self.tree.setCurrentIndex(QModelIndex())
        if not is_folder_mode:
            self.tree.expandToDepth(0)
        self._resize_tree_columns()

    def _select_root(self) -> None:
        if self._session is None:
            return
        if self._navigation_mode == "folders":
            if self._folder_model is None:
                return
            try:
                self._folder_model.set_group("/")
            except H5ViewerError as exc:
                self.status_message.emit(str(exc))
                return
            self._select_folder_group()
            return
        self.path_edit.setText("/")
        self.up_button.setEnabled(False)
        try:
            root = self._session.repository().root()
        except H5ViewerError as exc:
            self.status_message.emit(str(exc))
            return
        self.object_selected.emit(self._session, root)

    def _select_folder_group(self) -> None:
        """Показать путь текущей группы и сделать её активным объектом."""
        if self._session is None or self._folder_model is None:
            return
        path = self._folder_model.group_path
        self.path_edit.setText(path)
        self.up_button.setEnabled(path != "/")
        self.tree.setCurrentIndex(QModelIndex())
        try:
            link = self._session.repository().link(path)
        except H5ViewerError as exc:
            self.status_message.emit(str(exc))
            return
        self.object_selected.emit(self._session, link)

    def _go_up(self) -> None:
        """Перейти в родительскую группу в режиме папок."""
        if self._navigation_mode != "folders" or self._folder_model is None:
            return
        current = self._folder_model.group_path
        if current == "/":
            return
        parent_path, _name = split_hdf5_path(current)
        self._navigate_to_group(parent_path)

    def _navigate_to_group(self, path: str) -> None:
        """Загрузить непосредственное содержимое указанной группы."""
        if self._folder_model is None:
            return
        try:
            self._folder_model.set_group(path)
        except H5ViewerError as exc:
            self.status_message.emit(str(exc))
            return
        self._select_folder_group()

    def _refresh_folder_with_fallback(self) -> str:
        """Обновить папку или подняться до ближайшей сохранившейся группы."""
        assert self._folder_model is not None
        candidate = self._folder_model.group_path
        while True:
            try:
                self._folder_model.set_group(candidate)
                return candidate
            except H5ViewerError:
                if candidate == "/":
                    raise
                candidate, _name = split_hdf5_path(candidate)

    def _tree_clicked(self, proxy_index: Any) -> None:
        if self._model is None or self._session is None:
            return
        source = self._proxy.mapToSource(proxy_index.siblingAtColumn(0))
        link = self._proxy.sourceModel().data(source, HdfTreeModel.LinkRole)
        if isinstance(link, LinkRef):
            if self._navigation_mode == "tree":
                self.path_edit.setText(link.path)
            self.object_selected.emit(self._session, link)

    def _tree_double_clicked(self, proxy_index: Any) -> None:
        if not proxy_index.isValid():
            return
        link = self.current_link()
        if self._navigation_mode == "folders" and link is not None and link.can_expand:
            self._navigate_to_group(link.path)
            return
        if link is not None and not link.can_expand:
            self._open_current_link()
            return
        if self.tree.isExpanded(proxy_index):
            self.tree.collapse(proxy_index)
        else:
            self.tree.expand(proxy_index)

    def _activate_current_link(self) -> None:
        """Войти в группу режима папок либо открыть инспектор выбранного объекта."""
        link = self.current_link()
        if self._navigation_mode == "folders" and link is not None and link.can_expand:
            self._navigate_to_group(link.path)
            return
        self._open_current_link()

    def _open_current_link(self) -> None:
        """Открыть выбранный объект в отдельном инспекторе."""
        link = self.current_link()
        if self._session is not None and link is not None:
            self.object_open_requested.emit(self._session, link)

    def _show_context_menu(self, position: Any) -> None:
        if self._session is None:
            return
        link = self.current_link()
        menu = QMenu(self)
        inspect = QAction(tr("Pane", "Open inspector"), menu)
        inspect.setShortcut(QKeySequence(Qt.Key.Key_Return))
        inspect.setEnabled(link is not None)
        inspect.triggered.connect(self._open_current_link)
        menu.addAction(inspect)
        menu.addSeparator()
        create_group = QAction(tr("Pane", "Create group…"), menu)
        create_group.triggered.connect(lambda: self._create_group(link))
        menu.addAction(create_group)
        create_dataset = QAction(tr("Pane", "Create dataset…"), menu)
        create_dataset.triggered.connect(lambda: self._create_dataset(link))
        menu.addAction(create_dataset)
        create_link = QAction(tr("Pane", "Create link…"), menu)
        create_link.triggered.connect(lambda: self._create_link(link))
        menu.addAction(create_link)
        menu.addSeparator()
        rename = QAction(tr("Pane", "Rename…"), menu)
        rename.setEnabled(link is not None and link.path != "/")
        rename.triggered.connect(lambda: self._rename_link(link))
        menu.addAction(rename)
        move = QAction(tr("Pane", "Move to…"), menu)
        move.setEnabled(link is not None and link.path != "/")
        move.triggered.connect(lambda: self._move_link(link))
        menu.addAction(move)
        delete = QAction(tr("Pane", "Delete…"), menu)
        delete.setEnabled(link is not None and link.path != "/")
        delete.triggered.connect(lambda: self._delete_link(link))
        menu.addAction(delete)
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

    def _create_link(self, selected: LinkRef | None) -> None:
        """Создать HDF5-ссылку в выбранной или родительской группе."""
        if self._session is None:
            return
        parent_path = self._target_group(selected)
        dialog = LinkCreationDialog(parent_path, self._session.original_path, self)
        if dialog.exec() != LinkCreationDialog.DialogCode.Accepted:
            return
        if not self._ensure_editing(self._session):
            return
        request = dialog.request()
        try:
            self._session.execute(CreateLinkCommand(parent_path, request.name, request.options))
        except H5ViewerError as exc:
            QMessageBox.critical(self, tr("Dialog", "Error"), str(exc))
            return
        self.refresh()
        self.content_changed.emit(self._session)

    def _target_group(self, selected: LinkRef | None) -> str:
        """Выбрать группу назначения по текущему объекту панели."""
        if selected is None:
            if self._navigation_mode == "folders" and self._folder_model is not None:
                return self._folder_model.group_path
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

    def _move_link(self, selected: LinkRef | None) -> None:
        """Переместить ссылку по полному пути внутри текущего файла."""
        if self._session is None or selected is None or selected.path == "/":
            return
        destination, accepted = QInputDialog.getText(
            self,
            tr("Pane", "Move object"),
            tr("Pane", "Destination HDF5 path"),
            text=selected.path,
        )
        if not accepted or not destination or destination == selected.path:
            return
        if not self._ensure_editing(self._session):
            return
        try:
            self._session.execute(MoveLinkCommand(selected.path, destination))
        except H5ViewerError as exc:
            QMessageBox.critical(self, tr("Dialog", "Error"), str(exc))
            return
        self.refresh()
        self.content_changed.emit(self._session)

    def _delete_link(self, selected: LinkRef | None) -> None:
        """Удалить ссылку обратимой командой после подтверждения."""
        if self._session is None or selected is None or selected.path == "/":
            return
        answer = QMessageBox.question(
            self,
            tr("Dialog", "Confirm"),
            tr("Pane", "Delete the selected link and its unreferenced object?"),
        )
        if answer is not QMessageBox.StandardButton.Yes:
            return
        if not self._ensure_editing(self._session):
            return
        try:
            self._session.execute(DeleteLinkCommand(selected.path))
        except H5ViewerError as exc:
            QMessageBox.critical(self, tr("Dialog", "Error"), str(exc))
            return
        self.refresh()
        self.content_changed.emit(self._session)
