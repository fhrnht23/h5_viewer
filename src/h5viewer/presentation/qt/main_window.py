"""Главное двухпанельное окно приложения."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QSettings, QSize, Qt
from PySide6.QtGui import QAction, QActionGroup, QCloseEvent, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QInputDialog,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QToolBar,
    QToolButton,
    QVBoxLayout,
)

from h5viewer.application.commands import (
    CopyObjectCommand,
    DeleteLinkCommand,
    MoveLinkCommand,
)
from h5viewer.application.document import DocumentSession
from h5viewer.domain.errors import H5ViewerError
from h5viewer.domain.models import LinkRef, ObjectKind
from h5viewer.infrastructure.hdf5.copying import copy_hdf5_object
from h5viewer.infrastructure.hdf5.files import create_empty_hdf5
from h5viewer.infrastructure.hdf5.h5py_repository import H5pyRepository
from h5viewer.infrastructure.hdf5.validation import validate_hdf5_in_subprocess
from h5viewer.plugins.api import LocalizedText, ObjectSelection, PluginRegistration
from h5viewer.presentation.qt.analysis_dialogs import (
    FileComparisonDialog,
    MetadataSearchDialog,
)
from h5viewer.presentation.qt.formatting import format_byte_size
from h5viewer.presentation.qt.icons import interface_icon
from h5viewer.presentation.qt.inspector import ObjectInspector
from h5viewer.presentation.qt.pane import BrowserPane
from h5viewer.presentation.qt.settings_dialog import SettingsDialog
from h5viewer.presentation.qt.theme import ThemeManager
from h5viewer.presentation.qt.translations import LanguageManager, tr

if TYPE_CHECKING:
    from h5viewer.plugins.loader import PluginLoadReport, PluginManager


@dataclass(slots=True)
class CoordinatedMove:
    """Пара связанных команд межфайлового перемещения."""

    source_session: DocumentSession
    destination_session: DocumentSession
    source_command: DeleteLinkCommand
    destination_command: CopyObjectCommand
    applied: bool = True


class _QtPluginActionRegistration(PluginRegistration):
    """Одноразовый дескриптор удаления команды плагина из Qt-меню."""

    def __init__(self, remove_callback: Callable[[], None]) -> None:
        self._remove_callback: Callable[[], None] | None = remove_callback

    def remove(self) -> None:
        if self._remove_callback is None:
            return
        callback = self._remove_callback
        self._remove_callback = None
        callback()


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
        self._coordinated_moves: list[CoordinatedMove] = []
        self._active_session: DocumentSession | None = None
        self._active_link: LinkRef | None = None
        self._active_pane: BrowserPane | None = None
        self._plugin_manager: PluginManager | None = None
        self._plugin_actions: dict[tuple[str, str], tuple[QAction, LocalizedText]] = {}
        self._plugin_separator: QAction | None = None
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
        self.pane_splitter.setHandleWidth(10)
        self.pane_splitter.setContentsMargins(12, 12, 12, 10)
        self.setCentralWidget(self.pane_splitter)
        self.setMinimumSize(900, 560)

        self.inspector_window = QDialog(self, Qt.WindowType.Window)
        self.inspector_window.setObjectName("object_inspector_window")
        self.inspector_window.setModal(False)
        inspector_layout = QVBoxLayout(self.inspector_window)
        inspector_layout.setContentsMargins(12, 12, 12, 12)
        self.inspector = ObjectInspector(self.ensure_editing, self.inspector_window)
        inspector_layout.addWidget(self.inspector)
        self.inspector_window.resize(1050, 720)
        self.statusBar().setObjectName("mainStatusBar")
        self.statusBar().setSizeGripEnabled(False)
        self.statusBar().showMessage("")
        self._set_active_pane(self.left_pane)

    def _create_actions(self) -> None:
        self.new_action = QAction("", self)
        self.new_action.setShortcuts(
            [QKeySequence("Shift+F4"), QKeySequence(QKeySequence.StandardKey.New)]
        )
        self.new_action.triggered.connect(self.create_file)
        self.open_action = QAction("", self)
        self.open_action.setShortcut(QKeySequence.StandardKey.Open)
        self.open_action.triggered.connect(self.open_files)
        self.close_action = QAction("", self)
        self.close_action.setShortcut(QKeySequence.StandardKey.Close)
        self.close_action.triggered.connect(self.close_active_document)
        self.save_action = QAction("", self)
        self.save_action.setShortcut(QKeySequence.StandardKey.Save)
        self.save_action.triggered.connect(self.save_active)
        self.save_as_action = QAction("", self)
        self.save_as_action.setShortcut(QKeySequence.StandardKey.SaveAs)
        self.save_as_action.triggered.connect(self.save_active_as)
        self.discard_action = QAction("", self)
        self.discard_action.triggered.connect(self.discard_active)
        self.exit_action = QAction("", self)
        self.exit_action.setShortcuts(
            [QKeySequence("Alt+F4"), QKeySequence(QKeySequence.StandardKey.Quit)]
        )
        self.exit_action.triggered.connect(self.close)

        self.enable_edit_action = QAction("", self)
        self.enable_edit_action.setShortcut(QKeySequence("F4"))
        self.enable_edit_action.triggered.connect(self.enable_active_editing)
        self.open_inspector_action = QAction("", self)
        self.open_inspector_action.setShortcut(QKeySequence("F3"))
        self.open_inspector_action.triggered.connect(self.open_active_inspector)
        self.undo_action = QAction("", self)
        self.undo_action.setShortcut(QKeySequence.StandardKey.Undo)
        self.undo_action.triggered.connect(self.undo)
        self.redo_action = QAction("", self)
        self.redo_action.setShortcut(QKeySequence.StandardKey.Redo)
        self.redo_action.triggered.connect(self.redo)
        self.refresh_action = QAction("", self)
        self.refresh_action.setShortcuts([QKeySequence("F2"), QKeySequence("Ctrl+R")])
        self.refresh_action.triggered.connect(self.refresh_active)

        # Клавиши F5 и F6 повторяют Total Commander: источник определяется
        # активной панелью, а назначением всегда становится соседняя панель.
        self.copy_active_action = QAction("", self)
        self.copy_active_action.setShortcut(QKeySequence("F5"))
        self.copy_active_action.triggered.connect(self.copy_active_to_other)
        self.move_active_action = QAction("", self)
        self.move_active_action.setShortcut(QKeySequence("F6"))
        self.move_active_action.triggered.connect(self.move_active_to_other)
        self.create_group_action = QAction("", self)
        self.create_group_action.setShortcut(QKeySequence("F7"))
        self.create_group_action.triggered.connect(self.create_group_in_active_pane)
        self.create_group_other_action = QAction("", self)
        self.create_group_other_action.setShortcut(QKeySequence("Shift+F7"))
        self.create_group_other_action.triggered.connect(self.create_group_in_other_pane)
        self.rename_action = QAction("", self)
        self.rename_action.setShortcut(QKeySequence("Shift+F6"))
        self.rename_action.triggered.connect(self.rename_active_link)
        self.delete_action = QAction("", self)
        self.delete_action.setShortcuts([QKeySequence("F8"), QKeySequence("Delete")])
        self.delete_action.triggered.connect(self.delete_active_link)
        self.switch_pane_action = QAction("", self)
        self.switch_pane_action.setShortcuts([QKeySequence("Tab"), QKeySequence("Ctrl+I")])
        self.switch_pane_action.triggered.connect(self.switch_active_pane)
        self.toggle_navigation_action = QAction("", self)
        self.toggle_navigation_action.setShortcut(QKeySequence("Ctrl+F8"))
        self.toggle_navigation_action.triggered.connect(self.toggle_active_navigation_mode)

        # Направленные команды остаются отдельными кнопками для работы мышью.
        self.copy_right_action = QAction("", self)
        self.copy_right_action.triggered.connect(
            lambda: self.copy_between_panes(self.left_pane, self.right_pane)
        )
        self.copy_left_action = QAction("", self)
        self.copy_left_action.triggered.connect(
            lambda: self.copy_between_panes(self.right_pane, self.left_pane)
        )
        self.move_right_action = QAction("", self)
        self.move_right_action.triggered.connect(
            lambda: self.move_between_panes(self.left_pane, self.right_pane)
        )
        self.move_left_action = QAction("", self)
        self.move_left_action.triggered.connect(
            lambda: self.move_between_panes(self.right_pane, self.left_pane)
        )
        self.search_metadata_action = QAction("", self)
        self.search_metadata_action.setShortcuts(
            [QKeySequence("Alt+F7"), QKeySequence(QKeySequence.StandardKey.Find)]
        )
        self.search_metadata_action.triggered.connect(self.search_metadata)
        self.compare_panes_action = QAction("", self)
        self.compare_panes_action.setShortcut(QKeySequence("Ctrl+Shift+C"))
        self.compare_panes_action.triggered.connect(self.compare_pane_documents)

        self.dark_theme_action = QAction("", self, checkable=True)
        self.dark_theme_action.setChecked(self._theme_manager.dark)
        self.dark_theme_action.toggled.connect(self._theme_manager.apply)
        self.settings_action = QAction("", self)
        self.settings_action.setShortcut(QKeySequence("Ctrl+,"))
        self.settings_action.triggered.connect(self.show_settings)
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
        self._update_action_icons()

    def _create_menus(self) -> None:
        self.file_menu = self.menuBar().addMenu("")
        self.file_menu.addActions([self.new_action, self.open_action, self.close_action])
        self.file_menu.addSeparator()
        self.file_menu.addActions([self.save_action, self.save_as_action, self.discard_action])
        self.file_menu.addSeparator()
        self.file_menu.addAction(self.exit_action)
        self.edit_menu = self.menuBar().addMenu("")
        self.edit_menu.addActions(
            [
                self.enable_edit_action,
                self.undo_action,
                self.redo_action,
                self.open_inspector_action,
            ]
        )
        self.edit_menu.addSeparator()
        self.edit_menu.addActions(
            [
                self.copy_active_action,
                self.move_active_action,
                self.create_group_action,
                self.create_group_other_action,
                self.rename_action,
                self.delete_action,
            ]
        )
        self.edit_menu.addSeparator()
        self.edit_menu.addActions(
            [
                self.copy_right_action,
                self.copy_left_action,
                self.move_right_action,
                self.move_left_action,
            ]
        )
        self.view_menu = self.menuBar().addMenu("")
        self.view_menu.addActions(
            [
                self.switch_pane_action,
                self.toggle_navigation_action,
                self.refresh_action,
                self.dark_theme_action,
            ]
        )
        self.view_menu.addSeparator()
        self.view_menu.addAction(self.settings_action)
        self.tools_menu = self.menuBar().addMenu("")
        self.tools_menu.addActions([self.search_metadata_action, self.compare_panes_action])
        self.language_menu = self.menuBar().addMenu("")
        self.language_menu.addActions([self.russian_action, self.english_action])
        self.help_menu = self.menuBar().addMenu("")
        self.help_menu.addAction(self.about_action)

    def _create_toolbar(self) -> None:
        self.toolbar = QToolBar(self)
        self.toolbar.setObjectName("main_toolbar")
        self.toolbar.setMovable(False)
        self.toolbar.setFloatable(False)
        self.toolbar.setIconSize(QSize(18, 18))
        self.toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toolbar.addActions([self.new_action, self.open_action])
        self.toolbar.addSeparator()
        self.toolbar.addActions([self.enable_edit_action, self.save_action, self.discard_action])
        self.toolbar.addSeparator()
        self.toolbar.addActions([self.undo_action, self.redo_action, self.refresh_action])
        self.toolbar.addSeparator()
        self.toolbar.addActions(
            [
                self.copy_right_action,
                self.copy_left_action,
                self.move_right_action,
                self.move_left_action,
            ]
        )
        self.addToolBar(self.toolbar)

        # Часто используемые команды остаются подписанными, служебные занимают одну иконку.
        compact_actions = (
            self.undo_action,
            self.redo_action,
            self.refresh_action,
        )
        transfer_actions = (
            self.copy_right_action,
            self.copy_left_action,
            self.move_right_action,
            self.move_left_action,
        )
        for action in compact_actions:
            button = self.toolbar.widgetForAction(action)
            if isinstance(button, QToolButton):
                button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
                button.setProperty("compact", True)
        for action in transfer_actions:
            button = self.toolbar.widgetForAction(action)
            if isinstance(button, QToolButton):
                button.setProperty("transfer", True)
        open_button = self.toolbar.widgetForAction(self.open_action)
        if isinstance(open_button, QToolButton):
            open_button.setProperty("primary", True)

    def _connect_signals(self) -> None:
        for pane in (self.left_pane, self.right_pane):
            pane.object_selected.connect(self._show_object)
            pane.object_open_requested.connect(self._open_object_inspector)
            pane.document_changed.connect(self._activate_session)
            pane.content_changed.connect(self._content_changed)
            pane.status_message.connect(self.statusBar().showMessage)
            pane.activated.connect(self._set_active_pane)
        self.inspector.content_changed.connect(self._content_changed)
        self.inspector.dataset_resized.connect(self._dataset_resized)
        self.inspector.reference_activated.connect(self._open_reference_target)
        self.inspector.status_message.connect(self.statusBar().showMessage)
        self._language_manager.language_changed.connect(self._language_changed)
        self._theme_manager.theme_changed.connect(self._theme_changed)

    def _set_active_pane(self, active: BrowserPane) -> None:
        """Подсветить панель, в которой пользователь сейчас работает."""
        self._active_pane = active
        if active.session is not None:
            self._active_session = active.session
            self._active_link = active.current_link()
        for pane in (self.left_pane, self.right_pane):
            pane.setProperty("activePane", pane is active)
            pane.style().unpolish(pane)
            pane.style().polish(pane)
            pane.update()
        if hasattr(self, "open_inspector_action"):
            self._update_actions()
            self._update_title()

    def _theme_changed(self, _dark: bool) -> None:
        """Перерисовать зависящие от палитры векторные значки."""
        self.dark_theme_action.blockSignals(True)
        self.dark_theme_action.setChecked(self._theme_manager.dark)
        self.dark_theme_action.blockSignals(False)
        self._update_action_icons()
        for pane in (self.left_pane, self.right_pane):
            pane.refresh_visuals()

    def _update_action_icons(self) -> None:
        """Назначить всем кнопкам единообразные векторные значки."""
        icons = (
            (self.new_action, "new", False),
            (self.open_action, "open", True),
            (self.enable_edit_action, "edit", False),
            (self.save_action, "save", False),
            (self.discard_action, "discard", False),
            (self.undo_action, "undo", False),
            (self.redo_action, "redo", False),
            (self.refresh_action, "refresh", False),
            (self.copy_right_action, "copy_right", False),
            (self.copy_left_action, "copy_left", False),
            (self.move_right_action, "move_right", False),
            (self.move_left_action, "move_left", False),
            (self.settings_action, "settings", False),
        )
        for action, name, accent in icons:
            action.setIcon(interface_icon(name, accent=accent))

    def retranslate_ui(self) -> None:
        """Обновить меню, действия и дочерние виджеты после смены языка."""
        self.file_menu.setTitle(tr("MainWindow", "File"))
        self.edit_menu.setTitle(tr("MainWindow", "Edit"))
        self.view_menu.setTitle(tr("MainWindow", "View"))
        self.tools_menu.setTitle(tr("MainWindow", "Tools"))
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
            (self.open_inspector_action, "View object"),
            (self.undo_action, "Undo"),
            (self.redo_action, "Redo"),
            (self.refresh_action, "Refresh"),
            (self.copy_active_action, "Copy to other pane"),
            (self.move_active_action, "Move to other pane"),
            (self.create_group_action, "Create group in active pane"),
            (self.create_group_other_action, "Create group in other pane"),
            (self.rename_action, "Rename selected object"),
            (self.delete_action, "Delete selected object"),
            (self.switch_pane_action, "Switch active pane"),
            (self.toggle_navigation_action, "Tree / folder view"),
            (self.copy_right_action, "Copy →"),
            (self.copy_left_action, "← Copy"),
            (self.move_right_action, "Move →"),
            (self.move_left_action, "← Move"),
            (self.search_metadata_action, "Search metadata…"),
            (self.compare_panes_action, "Compare panes…"),
            (self.dark_theme_action, "Dark theme"),
            (self.settings_action, "Settings…"),
            (self.russian_action, "Russian"),
            (self.english_action, "English"),
            (self.about_action, "About"),
        )
        for action, source in action_texts:
            action.setText(tr("MainWindow", source))
        for action, title in self._plugin_actions.values():
            action.setText(title.resolve(self.language))
        toolbar_texts = (
            (self.new_action, "New"),
            (self.open_action, "Open"),
            (self.enable_edit_action, "Edit mode"),
            (self.save_action, "Save"),
            (self.discard_action, "Discard"),
            (self.undo_action, "Undo"),
            (self.redo_action, "Redo"),
            (self.refresh_action, "Refresh"),
            (self.copy_right_action, "Copy →"),
            (self.copy_left_action, "← Copy"),
            (self.move_right_action, "Move →"),
            (self.move_left_action, "← Move"),
        )
        for action, source in toolbar_texts:
            action.setIconText(tr("Toolbar", source))
        self.left_pane.retranslate_ui()
        self.right_pane.retranslate_ui()
        self.inspector.retranslate_ui()
        self._update_inspector_title()
        self._update_title()
        if self._active_link is not None:
            self.statusBar().showMessage(self._object_status_text(self._active_link))
        elif not self._documents:
            self.statusBar().showMessage(tr("MainWindow", "Ready"))

    @property
    def language(self) -> str:
        """Вернуть текущий язык для публичного API плагинов."""
        return self._language_manager.language

    def current_selection(self) -> ObjectSelection | None:
        """Подготовить стабильное описание выбранного объекта для плагина."""
        if self._active_session is None or self._active_link is None:
            return None
        return ObjectSelection(
            document_path=self._active_session.original_path,
            object_path=self._active_link.path,
            object_kind=self._active_link.object_kind.value,
            link_kind=self._active_link.link_kind.value,
            editing=self._active_session.is_editing,
        )

    def add_tools_action(
        self,
        plugin_id: str,
        action_id: str,
        title: LocalizedText,
        callback: Callable[[], None],
    ) -> PluginRegistration:
        """Добавить безопасно обёрнутую команду плагина в меню инструментов."""
        key = (plugin_id.strip(), action_id.strip())
        if not all(key):
            raise ValueError("plugin_id и action_id не должны быть пустыми")
        if key in self._plugin_actions:
            raise ValueError(f"Команда плагина уже зарегистрирована: {plugin_id}/{action_id}")
        if self._plugin_separator is None:
            self._plugin_separator = self.tools_menu.addSeparator()
        action = QAction(title.resolve(self.language), self)
        action.setObjectName(f"plugin:{key[0]}:{key[1]}")

        def invoke(_checked: bool = False) -> None:
            try:
                callback()
            except Exception as exc:
                self.show_information(
                    LocalizedText("Ошибка плагина", "Plugin error"),
                    LocalizedText(str(exc), str(exc)),
                )

        action.triggered.connect(invoke)
        self.tools_menu.addAction(action)
        self._plugin_actions[key] = (action, title)
        return _QtPluginActionRegistration(lambda: self._remove_plugin_action(key, action))

    def show_information(self, title: LocalizedText, message: LocalizedText) -> None:
        """Показать локализованное сообщение от плагина."""
        QMessageBox.information(
            self,
            title.resolve(self.language),
            message.resolve(self.language),
        )

    def show_status(self, message: LocalizedText, duration_ms: int = 5000) -> None:
        """Показать локализованное сообщение плагина в status bar."""
        self.statusBar().showMessage(message.resolve(self.language), duration_ms)

    def install_plugins(self, manager: PluginManager) -> PluginLoadReport:
        """Загрузить entry-point плагины после создания меню главного окна."""
        self._plugin_manager = manager
        report = manager.load(self)
        if report.issues:
            self.statusBar().showMessage(
                tr("MainWindow", "Plugins failed to load: {count}").format(
                    count=len(report.issues)
                ),
                8000,
            )
        return report

    def _remove_plugin_action(self, key: tuple[str, str], action: QAction) -> None:
        """Удалить только ту регистрацию, которой принадлежит дескриптор."""
        registered = self._plugin_actions.get(key)
        if registered is None or registered[0] is not action:
            return
        del self._plugin_actions[key]
        self.tools_menu.removeAction(action)
        action.deleteLater()
        if not self._plugin_actions and self._plugin_separator is not None:
            self.tools_menu.removeAction(self._plugin_separator)
            self._plugin_separator.deleteLater()
            self._plugin_separator = None

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
            self.inspector_window.hide()
        self._update_actions()
        self._update_title()

    def undo(self) -> None:
        if self._undo_coordinated_move():
            return
        if self._active_session is None:
            return
        try:
            self._active_session.undo()
        except H5ViewerError as exc:
            self._show_error(str(exc))
            return
        self._refresh_session(self._active_session)

    def redo(self) -> None:
        if self._redo_coordinated_move():
            return
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

    def _active_and_other_panes(self) -> tuple[BrowserPane, BrowserPane]:
        """Вернуть активную и соседнюю панели в порядке источник—назначение."""
        active = self._active_pane or self.left_pane
        other = self.right_pane if active is self.left_pane else self.left_pane
        return active, other

    def open_active_inspector(self) -> None:
        """Открыть выбранный объект активной панели клавишей F3."""
        active, _other = self._active_and_other_panes()
        active.open_current_link()

    def copy_active_to_other(self) -> None:
        """Скопировать объект из активной панели в соседнюю клавишей F5."""
        source, destination = self._active_and_other_panes()
        self.copy_between_panes(source, destination)

    def move_active_to_other(self) -> None:
        """Переместить объект из активной панели в соседнюю клавишей F6."""
        source, destination = self._active_and_other_panes()
        self.move_between_panes(source, destination)

    def create_group_in_active_pane(self) -> None:
        """Создать группу в активной панели клавишей F7."""
        active, _other = self._active_and_other_panes()
        active.create_group()

    def create_group_in_other_pane(self) -> None:
        """Создать группу в соседней панели клавишами Shift+F7."""
        _active, other = self._active_and_other_panes()
        other.create_group()

    def rename_active_link(self) -> None:
        """Переименовать выбранную ссылку активной панели."""
        active, _other = self._active_and_other_panes()
        active.rename_current_link()

    def delete_active_link(self) -> None:
        """Удалить выбранную ссылку активной панели."""
        active, _other = self._active_and_other_panes()
        active.delete_current_link()

    def switch_active_pane(self) -> None:
        """Передать фокус соседней панели как Tab в Total Commander."""
        _active, target = self._active_and_other_panes()
        target.tree.setFocus()
        self._set_active_pane(target)
        selected = target.current_link()
        if target.session is not None and selected is not None:
            self._show_object(target.session, selected)

    def toggle_active_navigation_mode(self) -> None:
        """Переключить дерево и папочный режим в активной панели."""
        active, _other = self._active_and_other_panes()
        active.toggle_navigation_mode()
        self._update_actions()

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

    def move_between_panes(self, source_pane: BrowserPane, destination_pane: BrowserPane) -> None:
        """Переместить выбранную ссылку внутри файла или между двумя рабочими копиями."""
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
                tr("MainWindow", "The root group cannot be moved"),
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
            tr("MainWindow", "Move object"),
            tr("MainWindow", "Destination name"),
            text=source_link.name,
        )
        if not accepted or not destination_name:
            return
        destination_path = (
            f"/{destination_name}"
            if destination_group == "/"
            else f"{destination_group}/{destination_name}"
        )
        if source_session is destination_session:
            if destination_path == source_link.path or not self.ensure_editing(source_session):
                return
            try:
                source_session.execute(MoveLinkCommand(source_link.path, destination_path))
            except H5ViewerError as exc:
                self._show_error(str(exc))
                return
            self._refresh_session(source_session)
            self.statusBar().showMessage(tr("MainWindow", "Object moved"), 5000)
            return

        answer = QMessageBox.warning(
            self,
            tr("Dialog", "Warning"),
            tr(
                "MainWindow",
                "Moving between files changes two independent working copies and cannot be saved "
                "atomically. Save the destination first, then the source, or discard both. "
                "Continue?",
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer is not QMessageBox.StandardButton.Yes:
            return
        destination_started = not destination_session.is_editing
        source_started = not source_session.is_editing
        if not self.ensure_editing(destination_session):
            return
        if not self.ensure_editing(source_session):
            if destination_started and not destination_session.is_dirty:
                destination_session.discard()
            return
        destination_command = CopyObjectCommand(
            source_file=source_session.active_path,
            source_path=source_link.path,
            destination_group=destination_group,
            destination_name=destination_name,
            copy_operation=copy_hdf5_object,
        )
        source_command = DeleteLinkCommand(source_link.path)
        try:
            destination_session.execute(destination_command)
            try:
                source_session.execute(source_command)
            except (H5ViewerError, OSError):
                destination_session.undo()
                destination_session.commands.discard_redo()
                raise
        except (H5ViewerError, OSError) as exc:
            if destination_started and not destination_session.is_dirty:
                destination_session.discard()
            if source_started and not source_session.is_dirty:
                source_session.discard()
            self._show_error(str(exc))
            return
        self._coordinated_moves.append(
            CoordinatedMove(
                source_session,
                destination_session,
                source_command,
                destination_command,
            )
        )
        self._refresh_session(source_session)
        self._refresh_session(destination_session)
        self._active_session = destination_session
        self._update_actions()
        self._update_title()
        self.statusBar().showMessage(
            tr("MainWindow", "Object moved; save destination, then source"),
            8000,
        )

    def show_about(self) -> None:
        QMessageBox.about(
            self,
            tr("MainWindow", "About H5 Viewer"),
            tr("MainWindow", "Cross-platform two-pane HDF5 viewer and safe editor."),
        )

    def show_settings(self) -> None:
        """Открыть общие настройки и справочник фактических сочетаний клавиш."""
        dialog = SettingsDialog(self._theme_manager, self.shortcut_descriptions(), self)
        dialog.exec()

    def shortcut_descriptions(self) -> list[tuple[str, str]]:
        """Собрать локализованный список назначений прямо из QAction."""
        actions = (
            self.open_inspector_action,
            self.enable_edit_action,
            self.new_action,
            self.copy_active_action,
            self.move_active_action,
            self.create_group_action,
            self.create_group_other_action,
            self.rename_action,
            self.delete_action,
            self.switch_pane_action,
            self.toggle_navigation_action,
            self.refresh_action,
            self.search_metadata_action,
            self.open_action,
            self.close_action,
            self.save_action,
            self.save_as_action,
            self.undo_action,
            self.redo_action,
            self.compare_panes_action,
            self.settings_action,
            self.exit_action,
        )
        format_ = QKeySequence.SequenceFormat.NativeText
        rows = [
            (
                action.text().replace("&", ""),
                ", ".join(sequence.toString(format_) for sequence in action.shortcuts()),
            )
            for action in actions
            if action.shortcuts()
        ]
        rows.extend(
            [
                (tr("Shortcuts", "Enter group or open inspector"), "Enter"),
                (tr("Pane", "Go to root group"), QKeySequence("Ctrl+\\").toString(format_)),
                (
                    tr("Pane", "Go to parent group"),
                    ", ".join(
                        QKeySequence(value).toString(format_)
                        for value in ("Ctrl+PgUp", "Backspace")
                    ),
                ),
            ]
        )
        return rows

    def _show_object(self, session: DocumentSession, link: LinkRef) -> None:
        self._active_session = session
        self._active_link = link
        self.inspector.show_object(session, link)
        self._update_inspector_title()
        self._update_actions()
        self._update_title()
        self.statusBar().showMessage(self._object_status_text(link))

    def _open_object_inspector(self, session: DocumentSession, link: LinkRef) -> None:
        """Показать выбранный объект в отдельном немодальном окне."""
        self._show_object(session, link)
        self.inspector_window.show()
        self.inspector_window.raise_()
        self.inspector_window.activateWindow()

    def _object_status_text(self, link: LinkRef) -> str:
        """Собрать краткую локализованную сводку для status bar."""
        parts = [link.path, tr("Type", link.object_kind.value)]
        if link.shape is not None:
            parts.append(f"shape={link.shape}")
        if link.dtype:
            parts.append(f"dtype={link.dtype}")
        if link.logical_bytes is not None:
            parts.append(
                f"{tr('MainWindow', 'Logical size')}: {format_byte_size(link.logical_bytes)}"
            )
        if link.storage_bytes is not None:
            parts.append(f"{tr('MainWindow', 'On disk')}: {format_byte_size(link.storage_bytes)}")
        if link.storage:
            parts.append(link.storage)
        if link.link_kind.value not in {"root", "hard"}:
            parts.append(f"link={tr('Type', link.link_kind.value)}")
        if link.child_count is not None:
            parts.append(f"{tr('MainWindow', 'Objects')}: {link.child_count}")
        if (
            self._active_pane is not None
            and self._active_pane.navigation_mode == "folders"
            and link.can_expand
        ):
            parts.append(tr("MainWindow", "Enter: open group"))
        else:
            parts.append(tr("MainWindow", "Enter: open inspector"))
        return " · ".join(parts)

    def _update_inspector_title(self) -> None:
        """Обновить заголовок отдельного окна инспектора."""
        title = tr("MainWindow", "Object inspector")
        if self._active_link is not None:
            title = f"{self._active_link.path} — {title}"
        self.inspector_window.setWindowTitle(title)

    def _open_reference_target(self, session: DocumentSession, path: str) -> None:
        """Открыть в инспекторе доступную цель object или region reference."""
        try:
            link = session.repository().link(path)
        except H5ViewerError as exc:
            self._show_error(str(exc))
            return
        self._open_object_inspector(session, link)
        self.statusBar().showMessage(tr("MainWindow", "Reference target opened"), 5000)

    def search_metadata(self) -> None:
        """Открыть поиск по metadata активного документа."""
        if self._active_session is None:
            return
        dialog = MetadataSearchDialog(self._active_session, self)
        dialog.path_activated.connect(self._open_analysis_path)
        dialog.exec()

    def compare_pane_documents(self) -> None:
        """Сравнить документы, выбранные в левой и правой панелях."""
        left_session = self.left_pane.session
        right_session = self.right_pane.session
        if left_session is None or right_session is None:
            return
        dialog = FileComparisonDialog(left_session, right_session, self)
        dialog.path_activated.connect(self._open_analysis_path)
        dialog.exec()

    def _open_analysis_path(self, session: DocumentSession, path: str) -> None:
        """Открыть путь из результата поиска или сравнения в инспекторе."""
        try:
            link = session.repository().link(path)
        except H5ViewerError as exc:
            self._show_error(str(exc))
            return
        self._open_object_inspector(session, link)

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
        try:
            updated = session.repository().link(path)
        except H5ViewerError:
            updated = None
        for pane in (self.left_pane, self.right_pane):
            pane.update_dataset_shape(
                session,
                path,
                object_token,
                shape,
                updated.logical_bytes if updated is not None else None,
                updated.storage_bytes if updated is not None else None,
            )
        if (
            self._active_session is session
            and self._active_link is not None
            and (
                self._active_link.path == path
                or bool(object_token and self._active_link.object_token == object_token)
            )
        ):
            self._active_link = replace(
                self._active_link,
                shape=shape,
                logical_bytes=(
                    updated.logical_bytes
                    if updated is not None
                    else self._active_link.logical_bytes
                ),
                storage_bytes=(
                    updated.storage_bytes
                    if updated is not None
                    else self._active_link.storage_bytes
                ),
            )
            self.statusBar().showMessage(self._object_status_text(self._active_link))

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
        active, other = self._active_and_other_panes()
        active_link = active.current_link()
        transferable = active_link is not None and active_link.path != "/"
        editable_link = transferable and active.session is not None
        self.close_action.setEnabled(has_document)
        self.save_action.setEnabled(editing)
        self.save_as_action.setEnabled(has_document)
        self.discard_action.setEnabled(editing)
        self.enable_edit_action.setEnabled(has_document and not editing)
        self.refresh_action.setEnabled(has_document)
        self.search_metadata_action.setEnabled(has_document)
        self.compare_panes_action.setEnabled(
            self.left_pane.session is not None and self.right_pane.session is not None
        )
        self.open_inspector_action.setEnabled(active_link is not None)
        self.copy_active_action.setEnabled(transferable and other.session is not None)
        self.move_active_action.setEnabled(transferable and other.session is not None)
        self.create_group_action.setEnabled(active.session is not None)
        self.create_group_other_action.setEnabled(other.session is not None)
        self.rename_action.setEnabled(editable_link)
        self.delete_action.setEnabled(editable_link)
        self.toggle_navigation_action.setEnabled(active.session is not None)
        left_link = self.left_pane.current_link()
        right_link = self.right_pane.current_link()
        left_transferable = left_link is not None and left_link.path != "/"
        right_transferable = right_link is not None and right_link.path != "/"
        self.copy_right_action.setEnabled(left_transferable and self.right_pane.session is not None)
        self.copy_left_action.setEnabled(right_transferable and self.left_pane.session is not None)
        self.move_right_action.setEnabled(left_transferable and self.right_pane.session is not None)
        self.move_left_action.setEnabled(right_transferable and self.left_pane.session is not None)
        self.undo_action.setEnabled(bool(session and session.commands.can_undo))
        self.redo_action.setEnabled(bool(session and session.commands.can_redo))

    def _undo_coordinated_move(self) -> bool:
        """Атомарно для UI отменить ближайшее парное перемещение."""
        for operation in reversed(self._coordinated_moves):
            if (
                operation.applied
                and self._active_session
                in {operation.source_session, operation.destination_session}
                and operation.source_session.commands.is_next_undo(operation.source_command)
                and operation.destination_session.commands.is_next_undo(
                    operation.destination_command
                )
            ):
                operation.source_session.undo()
                operation.destination_session.undo()
                operation.applied = False
                self._refresh_session(operation.source_session)
                self._refresh_session(operation.destination_session)
                self.statusBar().showMessage(tr("MainWindow", "Move undone"), 5000)
                return True
        return False

    def _redo_coordinated_move(self) -> bool:
        """Повторно применить ближайшее отменённое парное перемещение."""
        for operation in self._coordinated_moves:
            if (
                not operation.applied
                and self._active_session
                in {operation.source_session, operation.destination_session}
                and operation.source_session.commands.is_next_redo(operation.source_command)
                and operation.destination_session.commands.is_next_redo(
                    operation.destination_command
                )
            ):
                operation.destination_session.redo()
                operation.source_session.redo()
                operation.applied = True
                self._refresh_session(operation.source_session)
                self._refresh_session(operation.destination_session)
                self.statusBar().showMessage(tr("MainWindow", "Move repeated"), 5000)
                return True
        return False

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
        pane_sizes = self._settings.value("main/pane_splitter")
        inspector_geometry = self._settings.value("inspector/geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)
        else:
            self.resize(1400, 900)
        if state is not None:
            self.restoreState(state)
        if isinstance(pane_sizes, list):
            self.pane_splitter.setSizes([int(value) for value in pane_sizes])
        if inspector_geometry is not None:
            self.inspector_window.restoreGeometry(inspector_geometry)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        for session in list(self._documents):
            if not self._confirm_close_session(session):
                event.ignore()
                return
        self._settings.setValue("main/geometry", self.saveGeometry())
        self._settings.setValue("main/state", self.saveState())
        self._settings.setValue("main/pane_splitter", self.pane_splitter.sizes())
        self._settings.setValue("inspector/geometry", self.inspector_window.saveGeometry())
        if self._plugin_manager is not None:
            self._plugin_manager.close()
        self.inspector_window.close()
        event.accept()

    def _show_error(self, message: str) -> None:
        QMessageBox.critical(self, tr("Dialog", "Error"), message)


def active_window() -> MainWindow | None:
    """Вернуть главное окно текущего QApplication, если оно уже создано."""
    window = QApplication.activeWindow()
    return window if isinstance(window, MainWindow) else None
