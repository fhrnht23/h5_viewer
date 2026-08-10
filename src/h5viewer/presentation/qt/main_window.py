"""Главное двухпанельное окно приложения."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QAction, QActionGroup, QCloseEvent, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QInputDialog,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QStyle,
    QToolBar,
)

from h5viewer.application.commands import CopyObjectCommand
from h5viewer.application.document import DocumentSession
from h5viewer.domain.errors import H5ViewerError
from h5viewer.domain.models import LinkRef, ObjectKind
from h5viewer.infrastructure.hdf5.copying import copy_hdf5_object
from h5viewer.infrastructure.hdf5.files import create_empty_hdf5
from h5viewer.infrastructure.hdf5.h5py_repository import H5pyRepository
from h5viewer.infrastructure.hdf5.validation import validate_hdf5_in_subprocess
from h5viewer.presentation.qt.inspector import ObjectInspector
from h5viewer.presentation.qt.pane import BrowserPane
from h5viewer.presentation.qt.theme import ThemeManager
from h5viewer.presentation.qt.translations import LanguageManager, tr


class MainWindow(QMainWindow):
    """Координирует общие документы, две панели и инспектор."""

    def __init__(
        self,
        language_manager: LanguageManager,
        theme_manager: ThemeManager,
    ) -> None:
        super().__init__()
        self._language_manager = language_manager
        self._theme_manager = theme_manager
        self._settings = QSettings()
        self._documents: list[DocumentSession] = []
        self._active_session: DocumentSession | None = None
        self._active_link: LinkRef | None = None
        self._build_ui()
        self._create_actions()
        self._create_menus()
        self._create_toolbar()
        self._connect_signals()
        self._restore_window_state()
        self.retranslate_ui()
        self._update_actions()

    def _build_ui(self) -> None:
        self.left_pane = BrowserPane(self.ensure_editing, self)
        self.right_pane = BrowserPane(self.ensure_editing, self)
        self.pane_splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.pane_splitter.addWidget(self.left_pane)
        self.pane_splitter.addWidget(self.right_pane)
        self.pane_splitter.setChildrenCollapsible(False)
        self.pane_splitter.setStretchFactor(0, 1)
        self.pane_splitter.setStretchFactor(1, 1)

        self.inspector = ObjectInspector(self.ensure_editing, self)
        self.main_splitter = QSplitter(Qt.Orientation.Vertical, self)
        self.main_splitter.addWidget(self.pane_splitter)
        self.main_splitter.addWidget(self.inspector)
        self.main_splitter.setChildrenCollapsible(False)
        self.main_splitter.setStretchFactor(0, 3)
        self.main_splitter.setStretchFactor(1, 2)
        self.setCentralWidget(self.main_splitter)
        self.statusBar().showMessage("")

    def _create_actions(self) -> None:
        style = self.style()
        self.new_action = QAction(style.standardIcon(QStyle.StandardPixmap.SP_FileIcon), "", self)
        self.new_action.setShortcut(QKeySequence.StandardKey.New)
        self.new_action.triggered.connect(self.create_file)
        self.open_action = QAction(
            style.standardIcon(QStyle.StandardPixmap.SP_DialogOpenButton), "", self
        )
        self.open_action.setShortcut(QKeySequence.StandardKey.Open)
        self.open_action.triggered.connect(self.open_files)
        self.close_action = QAction("", self)
        self.close_action.setShortcut(QKeySequence.StandardKey.Close)
        self.close_action.triggered.connect(self.close_active_document)
        self.save_action = QAction(
            style.standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton), "", self
        )
        self.save_action.setShortcut(QKeySequence.StandardKey.Save)
        self.save_action.triggered.connect(self.save_active)
        self.save_as_action = QAction("", self)
        self.save_as_action.setShortcut(QKeySequence.StandardKey.SaveAs)
        self.save_as_action.triggered.connect(self.save_active_as)
        self.discard_action = QAction("", self)
        self.discard_action.triggered.connect(self.discard_active)
        self.exit_action = QAction("", self)
        self.exit_action.setShortcut(QKeySequence.StandardKey.Quit)
        self.exit_action.triggered.connect(self.close)

        self.enable_edit_action = QAction("", self)
        self.enable_edit_action.triggered.connect(self.enable_active_editing)
        self.undo_action = QAction(style.standardIcon(QStyle.StandardPixmap.SP_ArrowBack), "", self)
        self.undo_action.setShortcut(QKeySequence.StandardKey.Undo)
        self.undo_action.triggered.connect(self.undo)
        self.redo_action = QAction(
            style.standardIcon(QStyle.StandardPixmap.SP_ArrowForward), "", self
        )
        self.redo_action.setShortcut(QKeySequence.StandardKey.Redo)
        self.redo_action.triggered.connect(self.redo)
        self.refresh_action = QAction(
            style.standardIcon(QStyle.StandardPixmap.SP_BrowserReload), "", self
        )
        self.refresh_action.setShortcut(QKeySequence("Ctrl+R"))
        self.refresh_action.triggered.connect(self.refresh_active)
        self.copy_right_action = QAction("", self)
        self.copy_right_action.setShortcut("F5")
        self.copy_right_action.triggered.connect(
            lambda: self.copy_between_panes(self.left_pane, self.right_pane)
        )
        self.copy_left_action = QAction("", self)
        self.copy_left_action.setShortcut("Shift+F5")
        self.copy_left_action.triggered.connect(
            lambda: self.copy_between_panes(self.right_pane, self.left_pane)
        )

        self.dark_theme_action = QAction("", self, checkable=True)
        self.dark_theme_action.setChecked(self._theme_manager.dark)
        self.dark_theme_action.toggled.connect(self._theme_manager.apply)
        self.russian_action = QAction("", self, checkable=True)
        self.russian_action.setData("ru")
        self.english_action = QAction("", self, checkable=True)
        self.english_action.setData("en")
        language_group = QActionGroup(self)
        language_group.setExclusive(True)
        language_group.addAction(self.russian_action)
        language_group.addAction(self.english_action)
        language_group.triggered.connect(
            lambda action: self._language_manager.set_language(str(action.data()))
        )
        self.russian_action.setChecked(self._language_manager.language == "ru")
        self.english_action.setChecked(self._language_manager.language == "en")

        self.about_action = QAction("", self)
        self.about_action.triggered.connect(self.show_about)

    def _create_menus(self) -> None:
        self.file_menu = self.menuBar().addMenu("")
        self.file_menu.addActions([self.new_action, self.open_action, self.close_action])
        self.file_menu.addSeparator()
        self.file_menu.addActions([self.save_action, self.save_as_action, self.discard_action])
        self.file_menu.addSeparator()
        self.file_menu.addAction(self.exit_action)
        self.edit_menu = self.menuBar().addMenu("")
        self.edit_menu.addActions([self.enable_edit_action, self.undo_action, self.redo_action])
        self.edit_menu.addSeparator()
        self.edit_menu.addActions([self.copy_right_action, self.copy_left_action])
        self.view_menu = self.menuBar().addMenu("")
        self.view_menu.addActions([self.refresh_action, self.dark_theme_action])
        self.language_menu = self.menuBar().addMenu("")
        self.language_menu.addActions([self.russian_action, self.english_action])
        self.help_menu = self.menuBar().addMenu("")
        self.help_menu.addAction(self.about_action)

    def _create_toolbar(self) -> None:
        self.toolbar = QToolBar(self)
        self.toolbar.setObjectName("main_toolbar")
        self.toolbar.setMovable(True)
        self.toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toolbar.addActions([self.new_action, self.open_action])
        self.toolbar.addSeparator()
        self.toolbar.addActions([self.enable_edit_action, self.save_action, self.discard_action])
        self.toolbar.addSeparator()
        self.toolbar.addActions([self.undo_action, self.redo_action, self.refresh_action])
        self.toolbar.addSeparator()
        self.toolbar.addActions([self.copy_right_action, self.copy_left_action])
        self.addToolBar(self.toolbar)

    def _connect_signals(self) -> None:
        for pane in (self.left_pane, self.right_pane):
            pane.object_selected.connect(self._show_object)
            pane.document_changed.connect(self._activate_session)
            pane.content_changed.connect(self._content_changed)
            pane.status_message.connect(self.statusBar().showMessage)
        self.inspector.content_changed.connect(self._content_changed)
        self.inspector.dataset_resized.connect(self._dataset_resized)
        self.inspector.status_message.connect(self.statusBar().showMessage)
        self._language_manager.language_changed.connect(self._language_changed)

    def retranslate_ui(self) -> None:
        """Обновить меню, действия и дочерние виджеты после смены языка."""
        self.file_menu.setTitle(tr("MainWindow", "File"))
        self.edit_menu.setTitle(tr("MainWindow", "Edit"))
        self.view_menu.setTitle(tr("MainWindow", "View"))
        self.language_menu.setTitle(tr("MainWindow", "Language"))
        self.help_menu.setTitle(tr("MainWindow", "Help"))
        action_texts = (
            (self.new_action, "New file…"),
            (self.open_action, "Open…"),
            (self.close_action, "Close file"),
            (self.save_action, "Save"),
            (self.save_as_action, "Save As…"),
            (self.discard_action, "Discard changes"),
            (self.exit_action, "Exit"),
            (self.enable_edit_action, "Enable safe editing"),
            (self.undo_action, "Undo"),
            (self.redo_action, "Redo"),
            (self.refresh_action, "Refresh"),
            (self.copy_right_action, "Copy →"),
            (self.copy_left_action, "← Copy"),
            (self.dark_theme_action, "Dark theme"),
            (self.russian_action, "Russian"),
            (self.english_action, "English"),
            (self.about_action, "About"),
        )
        for action, source in action_texts:
            action.setText(tr("MainWindow", source))
        self.left_pane.retranslate_ui()
        self.right_pane.retranslate_ui()
        self.inspector.retranslate_ui()
        self._update_title()
        if not self._documents:
            self.statusBar().showMessage(tr("MainWindow", "Ready"))

    def create_file(self) -> None:
        """Создать пустой HDF5-файл и сразу открыть его."""
        filename, _filter = QFileDialog.getSaveFileName(
            self,
            tr("Dialog", "Create HDF5 file"),
            str(Path.home() / "new_file.h5"),
            tr("Dialog", "HDF5 files (*.h5 *.hdf5 *.he5);;All files (*)"),
        )
        if not filename:
            return
        path = Path(filename)
        if not path.suffix:
            path = path.with_suffix(".h5")
        try:
            create_empty_hdf5(path)
            self._open_path(path)
        except H5ViewerError as exc:
            self._show_error(str(exc))

    def open_files(self) -> None:
        """Выбрать и открыть один или несколько HDF5-файлов."""
        filenames, _filter = QFileDialog.getOpenFileNames(
            self,
            tr("Dialog", "Open HDF5 files"),
            str(Path.home()),
            tr("Dialog", "HDF5 files (*.h5 *.hdf5 *.he5);;All files (*)"),
        )
        for filename in filenames:
            self._open_path(Path(filename))

    def _open_path(self, path: Path) -> DocumentSession | None:
        resolved = path.expanduser().resolve()
        for document in self._documents:
            if document.original_path == resolved:
                self._activate_session(document)
                return document
        try:
            document = DocumentSession(
                resolved,
                lambda file_path, writable: H5pyRepository(file_path, writable=writable),
                file_validator=validate_hdf5_in_subprocess,
            )
        except (H5ViewerError, OSError) as exc:
            self._show_error(str(exc))
            return None
        self._documents.append(document)
        if len(self._documents) == 1:
            self.left_pane.set_documents(self._documents, document)
            self.right_pane.set_documents(self._documents, document)
        else:
            self.left_pane.set_documents(self._documents)
            self.right_pane.set_documents(self._documents, document)
        self._activate_session(document)
        return document

    def ensure_editing(self, session: DocumentSession) -> bool:
        """При необходимости запросить создание безопасной рабочей копии."""
        if session.is_editing:
            return True
        answer = QMessageBox.question(
            self,
            tr("Dialog", "Safe editing"),
            tr(
                "Dialog",
                "A working copy will be created next to the original file. Continue?",
            ),
        )
        if answer is not QMessageBox.StandardButton.Yes:
            return False
        try:
            session.begin_edit()
        except (H5ViewerError, OSError) as exc:
            self._show_error(str(exc))
            return False
        # Структура рабочей копии на этом шаге идентична оригиналу, поэтому
        # сохраняем текущий выбор и обновляем только редактор и состояния действий.
        if self._active_session is session and self._active_link is not None:
            self.inspector.refresh()
        self.statusBar().showMessage(tr("MainWindow", "Working copy created"), 5000)
        self._update_actions()
        return True

    def enable_active_editing(self) -> None:
        if self._active_session is not None:
            self.ensure_editing(self._active_session)

    def save_active(self) -> bool:
        """Проверить и атомарно зафиксировать активную рабочую копию."""
        session = self._active_session
        if session is None or not session.is_editing:
            return True
        try:
            result = session.save(create_backup=True)
        except (H5ViewerError, OSError) as exc:
            self._show_error(str(exc))
            return False
        self._refresh_session(session)
        message = tr("MainWindow", "Saved successfully")
        if result is not None and result.backup_path is not None:
            message += f" · {tr('MainWindow', 'Backup')}: {result.backup_path.name}"
        self.statusBar().showMessage(message, 8000)
        self._update_actions()
        return True

    def save_active_as(self) -> bool:
        session = self._active_session
        if session is None:
            return False
        filename, _filter = QFileDialog.getSaveFileName(
            self,
            tr("Dialog", "Save HDF5 file as"),
            str(session.original_path),
            tr("Dialog", "HDF5 files (*.h5 *.hdf5 *.he5);;All files (*)"),
        )
        if not filename:
            return False
        destination = Path(filename)
        if destination.exists() and destination.resolve() != session.original_path:
            answer = QMessageBox.question(
                self,
                tr("Dialog", "Confirm"),
                tr(
                    "Dialog",
                    "The destination already exists. It will be replaced after "
                    "a backup is created. Continue?",
                ),
            )
            if answer is not QMessageBox.StandardButton.Yes:
                return False
        try:
            session.save_as(destination, create_backup=True)
        except (H5ViewerError, OSError) as exc:
            self._show_error(str(exc))
            return False
        self._sync_document_lists(session)
        self._refresh_session(session)
        self.statusBar().showMessage(tr("MainWindow", "Saved successfully"), 8000)
        return True

    def discard_active(self) -> bool:
        session = self._active_session
        if session is None or not session.is_editing:
            return True
        answer = QMessageBox.question(
            self,
            tr("Dialog", "Confirm"),
            tr("Dialog", "Discard all changes in this file?"),
        )
        if answer is not QMessageBox.StandardButton.Yes:
            return False
        session.discard()
        self._refresh_session(session)
        self.statusBar().showMessage(tr("MainWindow", "Changes discarded"), 5000)
        self._update_actions()
        return True

    def close_active_document(self) -> None:
        session = self._active_session
        if session is None:
            return
        if not self._confirm_close_session(session):
            return
        self._documents.remove(session)
        preferred = self._documents[0] if self._documents else None
        self.left_pane.set_documents(self._documents, preferred)
        self.right_pane.set_documents(self._documents, preferred)
        self._active_session = preferred
        self._active_link = None
        if preferred is None:
            self.inspector.clear_inspector()
        self._update_actions()
        self._update_title()

    def undo(self) -> None:
        if self._active_session is None:
            return
        try:
            self._active_session.undo()
        except H5ViewerError as exc:
            self._show_error(str(exc))
            return
        self._refresh_session(self._active_session)

    def redo(self) -> None:
        if self._active_session is None:
            return
        try:
            self._active_session.redo()
        except H5ViewerError as exc:
            self._show_error(str(exc))
            return
        self._refresh_session(self._active_session)

    def refresh_active(self) -> None:
        if self._active_session is None:
            return
        if self._active_session.externally_modified and not self._active_session.is_editing:
            self.statusBar().showMessage(
                tr("MainWindow", "File changed outside the application"), 8000
            )
        try:
            self._active_session.reload()
        except (H5ViewerError, OSError) as exc:
            self._show_error(str(exc))
            return
        self._refresh_session(self._active_session)

    def copy_between_panes(self, source_pane: BrowserPane, destination_pane: BrowserPane) -> None:
        """Скопировать выбранный объект между панелями как отдельную undoable-команду."""
        source_session = source_pane.session
        destination_session = destination_pane.session
        source_link = source_pane.current_link()
        destination_link = destination_pane.current_link()
        if source_session is None or destination_session is None or source_link is None:
            QMessageBox.information(
                self,
                tr("Dialog", "Information"),
                tr("MainWindow", "Select a source object and a destination document"),
            )
            return
        if source_link.path == "/":
            QMessageBox.information(
                self,
                tr("Dialog", "Information"),
                tr("MainWindow", "The root group cannot be copied"),
            )
            return
        if source_session is not destination_session and source_session.is_editing:
            QMessageBox.warning(
                self,
                tr("Dialog", "Warning"),
                tr(
                    "MainWindow",
                    "Save or discard changes in the source file before copying it to another file",
                ),
            )
            return
        destination_group = "/"
        if destination_link is not None:
            destination_group = (
                destination_link.path
                if destination_link.object_kind is ObjectKind.GROUP
                else destination_link.parent_path
            )
        destination_name, accepted = QInputDialog.getText(
            self,
            tr("MainWindow", "Copy object"),
            tr("MainWindow", "Destination name"),
            text=source_link.name,
        )
        if not accepted or not destination_name:
            return
        answer = QMessageBox.question(
            self,
            tr("Dialog", "Confirm"),
            tr(
                "MainWindow",
                "The object will be copied without expanding soft/external links "
                "or references. Continue?",
            ),
        )
        if answer is not QMessageBox.StandardButton.Yes:
            return
        if not self.ensure_editing(destination_session):
            return
        try:
            destination_session.execute(
                CopyObjectCommand(
                    source_file=source_session.active_path,
                    source_path=source_link.path,
                    destination_group=destination_group,
                    destination_name=destination_name,
                    copy_operation=copy_hdf5_object,
                )
            )
        except H5ViewerError as exc:
            self._show_error(str(exc))
            return
        self._active_session = destination_session
        self._active_link = None
        self._refresh_session(destination_session)
        self.statusBar().showMessage(tr("MainWindow", "Object copied"), 5000)

    def show_about(self) -> None:
        QMessageBox.about(
            self,
            tr("MainWindow", "About H5 Viewer"),
            tr("MainWindow", "Cross-platform two-pane HDF5 viewer and safe editor."),
        )

    def _show_object(self, session: DocumentSession, link: LinkRef) -> None:
        self._active_session = session
        self._active_link = link
        self.inspector.show_object(session, link)
        self._update_actions()
        self._update_title()

    def _activate_session(self, session: DocumentSession) -> None:
        self._active_session = session
        self._active_link = None
        self._update_actions()
        self._update_title()

    def _content_changed(self, session: DocumentSession) -> None:
        if self.sender() is self.inspector:
            self._update_actions()
            self._update_title()
            return
        self._refresh_session(session)

    def _dataset_resized(
        self,
        session: DocumentSession,
        path: str,
        object_token: str | None,
        shape: tuple[int, ...],
    ) -> None:
        """Синхронизировать форму dataset в обеих панелях без сброса выбора."""
        for pane in (self.left_pane, self.right_pane):
            pane.update_dataset_shape(session, path, object_token, shape)
        if (
            self._active_session is session
            and self._active_link is not None
            and (
                self._active_link.path == path
                or bool(object_token and self._active_link.object_token == object_token)
            )
        ):
            self._active_link = replace(self._active_link, shape=shape)

    def _refresh_session(self, session: DocumentSession) -> None:
        for pane in (self.left_pane, self.right_pane):
            if pane.session is session:
                pane.refresh()
        if self._active_session is session and self._active_link is not None:
            self.inspector.refresh()
        self._update_actions()
        self._update_title()

    def _sync_document_lists(self, preferred: DocumentSession | None = None) -> None:
        self.left_pane.set_documents(self._documents, preferred or self.left_pane.session)
        self.right_pane.set_documents(self._documents, preferred or self.right_pane.session)

    def _update_actions(self) -> None:
        session = self._active_session
        has_document = session is not None
        editing = bool(session and session.is_editing)
        self.close_action.setEnabled(has_document)
        self.save_action.setEnabled(editing)
        self.save_as_action.setEnabled(has_document)
        self.discard_action.setEnabled(editing)
        self.enable_edit_action.setEnabled(has_document and not editing)
        self.refresh_action.setEnabled(has_document)
        can_copy = bool(self.left_pane.current_link() or self.right_pane.current_link())
        self.copy_right_action.setEnabled(has_document and can_copy)
        self.copy_left_action.setEnabled(has_document and can_copy)
        self.undo_action.setEnabled(bool(session and session.commands.can_undo))
        self.redo_action.setEnabled(bool(session and session.commands.can_redo))

    def _update_title(self) -> None:
        title = tr("MainWindow", "H5 Viewer")
        if self._active_session is not None:
            marker = " *" if self._active_session.is_dirty else ""
            title = f"{self._active_session.original_path.name}{marker} — {title}"
        self.setWindowTitle(title)

    def _language_changed(self, language: str) -> None:
        self.russian_action.setChecked(language == "ru")
        self.english_action.setChecked(language == "en")
        self.retranslate_ui()
        self.statusBar().showMessage(tr("MainWindow", "Language changed"), 3000)

    def _confirm_close_session(self, session: DocumentSession) -> bool:
        if not session.is_editing:
            return True
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle(tr("Dialog", "Warning"))
        box.setText(tr("Dialog", "The file has unsaved changes."))
        box.setInformativeText(tr("Dialog", "Save changes before closing?"))
        box.setStandardButtons(
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel
        )
        answer = box.exec()
        if answer == QMessageBox.StandardButton.Save:
            previous = self._active_session
            self._active_session = session
            success = self.save_active()
            self._active_session = previous
            return success
        if answer == QMessageBox.StandardButton.Discard:
            session.discard()
            return True
        return False

    def _restore_window_state(self) -> None:
        geometry = self._settings.value("main/geometry")
        state = self._settings.value("main/state")
        main_sizes = self._settings.value("main/splitter")
        pane_sizes = self._settings.value("main/pane_splitter")
        if geometry is not None:
            self.restoreGeometry(geometry)
        else:
            self.resize(1400, 900)
        if state is not None:
            self.restoreState(state)
        if isinstance(main_sizes, list):
            self.main_splitter.setSizes([int(value) for value in main_sizes])
        if isinstance(pane_sizes, list):
            self.pane_splitter.setSizes([int(value) for value in pane_sizes])

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        for session in list(self._documents):
            if not self._confirm_close_session(session):
                event.ignore()
                return
        self._settings.setValue("main/geometry", self.saveGeometry())
        self._settings.setValue("main/state", self.saveState())
        self._settings.setValue("main/splitter", self.main_splitter.sizes())
        self._settings.setValue("main/pane_splitter", self.pane_splitter.sizes())
        event.accept()

    def _show_error(self, message: str) -> None:
        QMessageBox.critical(self, tr("Dialog", "Error"), message)


def active_window() -> MainWindow | None:
    """Вернуть главное окно текущего QApplication, если оно уже создано."""
    window = QApplication.activeWindow()
    return window if isinstance(window, MainWindow) else None
