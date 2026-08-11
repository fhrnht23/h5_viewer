"""Инспектор выбранного объекта HDF5."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QSpinBox,
    QTableView,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from h5viewer.application.commands import (
    DeleteAttributeCommand,
    ResizeDatasetCommand,
    SetAttributeCommand,
)
from h5viewer.application.document import DocumentSession
from h5viewer.domain.errors import H5ViewerError
from h5viewer.domain.models import (
    AttributeInfo,
    DatasetExportOptions,
    DatasetSlice,
    ExportFormat,
    GroupSizeReport,
    LinkRef,
    ObjectDetails,
    ObjectKind,
    ReferenceInfo,
    ReferenceSourceKind,
    default_dataset_slice,
)
from h5viewer.infrastructure.hdf5.analysis import calculate_group_size
from h5viewer.infrastructure.hdf5.exporting import export_hdf5_dataset
from h5viewer.presentation.qt.dialogs import ResizeDatasetDialog
from h5viewer.presentation.qt.formatting import format_byte_size
from h5viewer.presentation.qt.models import DatasetTableModel
from h5viewer.presentation.qt.translations import tr
from h5viewer.presentation.qt.visualization import (
    VisualizationUnavailableError,
    create_visualization_dialog,
)

EnsureEditing = Callable[[DocumentSession], bool]

_PROPERTY_LABELS = {
    "path": "Path",
    "object_kind": "Object kind",
    "object_token": "Object token",
    "attribute_count": "Attribute count",
    "file": "File",
    "file_size": "File size",
    "driver": "Driver",
    "libver": "HDF5 library bounds",
    "userblock_size": "User block size",
    "hdf5_version": "HDF5 version",
    "h5py_version": "h5py version",
    "member_count": "Direct members",
    "shape": "Shape",
    "rank": "Rank",
    "dtype": "Dtype",
    "size": "Elements",
    "logical_bytes": "Logical size",
    "storage_bytes": "On disk",
    "layout": "Layout",
    "chunks": "Chunks",
    "maxshape": "Maximum shape",
    "compression": "Compression",
    "compression_options": "Compression options",
    "shuffle": "Shuffle filter",
    "fletcher32": "Fletcher32 checksum",
    "scaleoffset": "Scale-offset filter",
    "fill_value": "Fill value",
    "is_virtual": "Virtual dataset",
    "is_dimension_scale": "Dimension scale",
    "external_storage": "External raw storage",
    "filter_ids": "Filter identifiers",
    "filter_names": "Filter names",
    "virtual_source_count": "Virtual sources",
    "dimension_labels": "Dimension labels",
    "recursive_dataset_count": "Unique datasets recursively",
    "recursive_group_count": "Unique groups recursively",
    "recursive_logical_bytes": "Recursive logical size",
    "recursive_storage_bytes": "Recursive size on disk",
    "scanned_links": "Scanned links",
    "duplicate_objects": "Aliases and cycles excluded",
    "external_links_skipped": "External links skipped",
    "unresolved_links": "Unresolved links",
    "virtual_dataset_count": "Virtual datasets",
}
_BYTE_PROPERTIES = {
    "file_size",
    "userblock_size",
    "logical_bytes",
    "storage_bytes",
    "recursive_logical_bytes",
    "recursive_storage_bytes",
}


class ObjectInspector(QTabWidget):
    """Показывает свойства, атрибуты и ограниченный срез dataset."""

    content_changed = Signal(object)
    dataset_resized = Signal(object, str, object, object)
    reference_activated = Signal(object, str)
    status_message = Signal(str)

    def __init__(
        self,
        ensure_editing: EnsureEditing,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._ensure_editing = ensure_editing
        self._session: DocumentSession | None = None
        self._link: LinkRef | None = None
        self._details: ObjectDetails | None = None
        self._group_size_report: GroupSizeReport | None = None
        self._dataset_shape: tuple[int, ...] | None = None
        self._build_ui()
        self.retranslate_ui()
        self.clear_inspector()

    def _build_ui(self) -> None:
        self.data_page = QWidget(self)
        data_layout = QVBoxLayout(self.data_page)
        projection = QFormLayout()
        self.row_axis_label = QLabel(self.data_page)
        self.column_axis_label = QLabel(self.data_page)
        self.fixed_indices_label = QLabel(self.data_page)
        self.row_axis = QComboBox(self.data_page)
        self.column_axis = QComboBox(self.data_page)
        self.fixed_indices = QLineEdit(self.data_page)
        self.row_offset = QSpinBox(self.data_page)
        self.column_offset = QSpinBox(self.data_page)
        for spinbox in (self.row_offset, self.column_offset):
            spinbox.setRange(0, 2_000_000_000)
            spinbox.setGroupSeparatorShown(True)
        self.load_page_button = QPushButton(self.data_page)
        self.load_page_button.clicked.connect(self._load_dataset_page)
        self.resize_dataset_button = QPushButton(self.data_page)
        self.resize_dataset_button.clicked.connect(self._resize_dataset)
        projection.addRow(self.row_axis_label, self.row_axis)
        projection.addRow(self.column_axis_label, self.column_axis)
        projection.addRow(self.fixed_indices_label, self.fixed_indices)
        offsets = QHBoxLayout()
        self.row_offset_label = QLabel(self.data_page)
        self.column_offset_label = QLabel(self.data_page)
        offsets.addWidget(self.row_offset_label)
        offsets.addWidget(self.row_offset)
        offsets.addWidget(self.column_offset_label)
        offsets.addWidget(self.column_offset)
        offsets.addWidget(self.load_page_button)
        offsets.addWidget(self.resize_dataset_button)
        projection.addRow(offsets)
        data_layout.addLayout(projection)
        dataset_actions = QHBoxLayout()
        self.export_dataset_button = QPushButton(self.data_page)
        self.visualize_dataset_button = QPushButton(self.data_page)
        self.export_dataset_button.clicked.connect(self._export_dataset)
        self.visualize_dataset_button.clicked.connect(self._visualize_dataset)
        dataset_actions.addWidget(self.export_dataset_button)
        dataset_actions.addWidget(self.visualize_dataset_button)
        dataset_actions.addStretch(1)
        data_layout.addLayout(dataset_actions)
        self.data_message = QLabel(self.data_page)
        self.data_message.setWordWrap(True)
        data_layout.addWidget(self.data_message)
        self.dataset_model = DatasetTableModel(self)
        self.dataset_model.edit_failed.connect(self._show_error)
        self.dataset_model.content_changed.connect(self._data_changed)
        self.data_table = QTableView(self.data_page)
        self.data_table.setModel(self.dataset_model)
        self.data_table.setAlternatingRowColors(True)
        self.data_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self.data_table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        data_layout.addWidget(self.data_table, 1)

        self.attributes_page = QWidget(self)
        attributes_layout = QVBoxLayout(self.attributes_page)
        self.attributes_table = QTableWidget(0, 4, self.attributes_page)
        self.attributes_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.attributes_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.attributes_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.attributes_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self.attributes_table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.Stretch
        )
        self.attributes_table.doubleClicked.connect(self._edit_attribute)
        attributes_layout.addWidget(self.attributes_table, 1)
        attribute_buttons = QHBoxLayout()
        self.add_attribute_button = QPushButton(self.attributes_page)
        self.edit_attribute_button = QPushButton(self.attributes_page)
        self.delete_attribute_button = QPushButton(self.attributes_page)
        self.add_attribute_button.clicked.connect(self._add_attribute)
        self.edit_attribute_button.clicked.connect(self._edit_attribute)
        self.delete_attribute_button.clicked.connect(self._delete_attribute)
        attribute_buttons.addWidget(self.add_attribute_button)
        attribute_buttons.addWidget(self.edit_attribute_button)
        attribute_buttons.addWidget(self.delete_attribute_button)
        attribute_buttons.addStretch(1)
        attributes_layout.addLayout(attribute_buttons)

        self.properties_page = QWidget(self)
        properties_layout = QVBoxLayout(self.properties_page)
        self.group_size_summary = QLabel(self.properties_page)
        self.group_size_summary.setWordWrap(True)
        properties_layout.addWidget(self.group_size_summary)
        properties_commands = QHBoxLayout()
        self.calculate_group_size_button = QPushButton(self.properties_page)
        self.calculate_group_size_button.clicked.connect(self._calculate_group_size)
        properties_commands.addWidget(self.calculate_group_size_button)
        properties_commands.addStretch(1)
        properties_layout.addLayout(properties_commands)
        self.properties_table = QTableWidget(0, 2, self.properties_page)
        self.properties_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.properties_table.verticalHeader().hide()
        self.properties_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self.properties_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        properties_layout.addWidget(self.properties_table, 1)

        self.links_page = QWidget(self)
        links_layout = QVBoxLayout(self.links_page)
        self.link_summary = QTextEdit(self.links_page)
        self.link_summary.setReadOnly(True)
        self.link_summary.setMaximumHeight(112)
        links_layout.addWidget(self.link_summary)

        self.metadata_tabs = QTabWidget(self.links_page)
        self.references_table = self._metadata_table(4, self.metadata_tabs)
        self.dimension_scales_table = self._metadata_table(3, self.metadata_tabs)
        self.virtual_mappings_table = self._metadata_table(4, self.metadata_tabs)
        self.metadata_tabs.addTab(self.references_table, "")
        self.metadata_tabs.addTab(self.dimension_scales_table, "")
        self.metadata_tabs.addTab(self.virtual_mappings_table, "")
        links_layout.addWidget(self.metadata_tabs, 1)
        reference_buttons = QHBoxLayout()
        self.open_reference_button = QPushButton(self.links_page)
        self.open_reference_button.setEnabled(False)
        self.open_reference_button.clicked.connect(self._navigate_reference)
        self.references_table.itemSelectionChanged.connect(self._reference_selection_changed)
        self.references_table.cellDoubleClicked.connect(
            lambda _row, _column: self._navigate_reference()
        )
        reference_buttons.addWidget(self.open_reference_button)
        reference_buttons.addStretch(1)
        links_layout.addLayout(reference_buttons)

        self.preview_text = QTextEdit(self)
        self.preview_text.setReadOnly(True)
        self.raw_text = QTextEdit(self)
        self.raw_text.setReadOnly(True)
        self.raw_text.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)

        self.addTab(self.data_page, "")
        self.addTab(self.attributes_page, "")
        self.addTab(self.properties_page, "")
        self.addTab(self.links_page, "")
        self.addTab(self.preview_text, "")
        self.addTab(self.raw_text, "")

    def _metadata_table(self, columns: int, parent: QWidget) -> QTableWidget:
        """Создать единообразную read-only таблицу метаданных."""
        table = QTableWidget(0, columns, parent)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.verticalHeader().hide()
        table.horizontalHeader().setStretchLastSection(True)
        return table

    def retranslate_ui(self) -> None:
        """Повторно перевести статические подписи инспектора."""
        labels = (
            tr("Inspector", "Data"),
            tr("Inspector", "Attributes"),
            tr("Inspector", "Properties"),
            tr("Inspector", "Links / References"),
            tr("Inspector", "Preview"),
            tr("Inspector", "Raw / DDL"),
        )
        for index, label in enumerate(labels):
            self.setTabText(index, label)
        self.row_axis_label.setText(tr("Inspector", "Row axis"))
        self.column_axis_label.setText(tr("Inspector", "Column axis"))
        self.fixed_indices_label.setText(tr("Inspector", "Fixed indices"))
        self.row_offset_label.setText(tr("Inspector", "Row offset"))
        self.column_offset_label.setText(tr("Inspector", "Column offset"))
        self.load_page_button.setText(tr("Inspector", "Load page"))
        self.resize_dataset_button.setText(tr("Inspector", "Resize…"))
        self.export_dataset_button.setText(tr("Inspector", "Export…"))
        self.visualize_dataset_button.setText(tr("Inspector", "Visualize…"))
        self.add_attribute_button.setText(tr("Inspector", "Add"))
        self.edit_attribute_button.setText(tr("Inspector", "Change"))
        self.delete_attribute_button.setText(tr("Inspector", "Delete"))
        self.calculate_group_size_button.setText(tr("Inspector", "Calculate recursive size…"))
        self.attributes_table.setHorizontalHeaderLabels(
            [
                tr("Inspector", "Name"),
                tr("Inspector", "Dtype"),
                tr("Inspector", "Shape"),
                tr("Inspector", "Value"),
            ]
        )
        self.properties_table.setHorizontalHeaderLabels(
            [tr("Inspector", "Property"), tr("Inspector", "Value")]
        )
        self.metadata_tabs.setTabText(0, tr("Inspector", "References"))
        self.metadata_tabs.setTabText(1, tr("Inspector", "Dimension scales"))
        self.metadata_tabs.setTabText(2, tr("Inspector", "VDS mappings"))
        self.references_table.setHorizontalHeaderLabels(
            [
                tr("Inspector", "Source"),
                tr("Inspector", "Kind"),
                tr("Inspector", "Target"),
                tr("Inspector", "Details"),
            ]
        )
        self.dimension_scales_table.setHorizontalHeaderLabels(
            [
                tr("Inspector", "Axis"),
                tr("Inspector", "Label"),
                tr("Inspector", "Attached scales"),
            ]
        )
        self.virtual_mappings_table.setHorizontalHeaderLabels(
            [
                tr("Inspector", "Source file"),
                tr("Inspector", "Source dataset"),
                tr("Inspector", "Source selection"),
                tr("Inspector", "Virtual selection"),
            ]
        )
        self.open_reference_button.setText(tr("Inspector", "Go to target"))
        if self._link is not None and self._details is not None:
            self._populate_properties(self._details)
            self._update_group_size_summary()
            self._populate_link_info(self._link, self._details)
            self._populate_raw(self._details)

    def clear_inspector(self) -> None:
        """Очистить содержимое при закрытии последнего документа."""
        self._session = None
        self._link = None
        self._details = None
        self._group_size_report = None
        self._dataset_shape = None
        self.dataset_model.clear()
        self.attributes_table.setRowCount(0)
        self.properties_table.setRowCount(0)
        self.calculate_group_size_button.hide()
        self.group_size_summary.hide()
        self.link_summary.clear()
        self.references_table.setRowCount(0)
        self.dimension_scales_table.setRowCount(0)
        self.virtual_mappings_table.setRowCount(0)
        self.open_reference_button.setEnabled(False)
        self.preview_text.setPlainText(tr("Inspector", "Select an object to inspect it"))
        self.raw_text.clear()
        self.data_message.setText(tr("Inspector", "Select a dataset"))
        self._set_dataset_controls_enabled(False)
        self._set_dataset_actions_enabled(False, False)

    def show_object(self, session: DocumentSession, link: LinkRef) -> None:
        """Показать выбранную ссылку и, если возможно, её целевой объект."""
        self._session = session
        self._link = link
        self._group_size_report = None
        self._dataset_shape = link.shape
        is_group = link.object_kind is ObjectKind.GROUP
        self.calculate_group_size_button.setVisible(is_group)
        self.calculate_group_size_button.setEnabled(is_group)
        self.group_size_summary.setVisible(is_group)
        self._update_group_size_summary()
        if link.object_kind is ObjectKind.BROKEN_LINK:
            self._details = None
            self._show_broken_link(link)
            return
        try:
            self._details = session.repository().details(link.path)
        except H5ViewerError as exc:
            self._details = None
            self._show_broken_link(link, str(exc))
            return
        self._populate_properties(self._details)
        self._populate_attributes(self._details.attributes)
        self._populate_link_info(link, self._details)
        self._populate_raw(self._details)
        if link.object_kind is ObjectKind.DATASET and link.shape is not None:
            self._set_dataset_actions_enabled(True, False)
            self.resize_dataset_button.setEnabled(bool(link.shape))
            self._configure_dataset(link.shape)
            self._load_dataset_page()
            self.setCurrentWidget(self.data_page)
        elif link.object_kind is ObjectKind.DATASET:
            self._set_dataset_actions_enabled(False, False)
            self._set_dataset_controls_enabled(False)
            self.dataset_model.clear()
            self.data_message.setText(tr("Inspector", "No data"))
        else:
            self._set_dataset_actions_enabled(False, False)
            self._set_dataset_controls_enabled(False)
            self.dataset_model.clear()
            self.data_message.setText(tr("Inspector", "Select a dataset"))
            self.preview_text.setPlainText(
                tr("Inspector", "No preview is available for this object")
            )

    def refresh(self) -> None:
        """Повторно прочитать текущий объект после изменения или undo/redo."""
        if self._session is not None and self._link is not None:
            self.show_object(self._session, self._link)

    def _configure_dataset(self, shape: tuple[int, ...]) -> None:
        selection = default_dataset_slice(shape)
        self.row_axis.blockSignals(True)
        self.column_axis.blockSignals(True)
        self.row_axis.clear()
        self.column_axis.clear()
        for axis, size in enumerate(shape):
            label = f"{axis} ({size})"
            self.row_axis.addItem(label, axis)
            self.column_axis.addItem(label, axis)
        self.column_axis.insertItem(0, "—", None)
        if selection.row_axis is not None:
            self.row_axis.setCurrentIndex(selection.row_axis)
        if selection.column_axis is None:
            self.column_axis.setCurrentIndex(0)
        else:
            self.column_axis.setCurrentIndex(selection.column_axis + 1)
        self.row_axis.blockSignals(False)
        self.column_axis.blockSignals(False)
        self.fixed_indices.setText(",".join(str(index) for index in selection.fixed_indices))
        self.row_offset.setValue(0)
        self.column_offset.setValue(0)
        enabled = bool(shape)
        for widget in (
            self.row_axis,
            self.column_axis,
            self.fixed_indices,
            self.row_offset,
            self.column_offset,
            self.load_page_button,
        ):
            widget.setEnabled(enabled)

    def _set_dataset_controls_enabled(self, enabled: bool) -> None:
        """Единообразно переключить элементы управления dataset."""
        for widget in (
            self.row_axis,
            self.column_axis,
            self.fixed_indices,
            self.row_offset,
            self.column_offset,
            self.load_page_button,
            self.resize_dataset_button,
        ):
            widget.setEnabled(enabled)

    def _set_dataset_actions_enabled(
        self,
        export_enabled: bool,
        visualization_enabled: bool,
    ) -> None:
        """Переключить действия, зависящие от доступной страницы dataset."""
        self.export_dataset_button.setEnabled(export_enabled)
        self.visualize_dataset_button.setEnabled(visualization_enabled)

    def _selection(self) -> DatasetSlice | None:
        if self._dataset_shape is None:
            return None
        if not self._dataset_shape:
            return DatasetSlice(None, None, ())
        try:
            fixed = tuple(int(value.strip()) for value in self.fixed_indices.text().split(","))
        except ValueError:
            self._show_error(tr("Inspector", "Invalid fixed indices"))
            return None
        if len(fixed) != len(self._dataset_shape):
            self._show_error(tr("Inspector", "Invalid fixed indices"))
            return None
        row_axis = self.row_axis.currentData()
        column_axis = self.column_axis.currentData()
        if column_axis == row_axis:
            self._show_error(tr("Inspector", "Invalid fixed indices"))
            return None
        return DatasetSlice(
            row_axis=int(row_axis),
            column_axis=None if column_axis is None else int(column_axis),
            fixed_indices=fixed,
            row_offset=self.row_offset.value(),
            column_offset=self.column_offset.value(),
        )

    def _load_dataset_page(self) -> None:
        if self._session is None or self._link is None:
            return
        selection = self._selection()
        if selection is None:
            return
        self.visualize_dataset_button.setEnabled(False)
        self.dataset_model.load(self._session, self._link.path, selection)
        if self.dataset_model.error:
            self.data_message.setText(self.dataset_model.error)
            return
        page = self.dataset_model.page
        if page is None:
            self.data_message.setText(tr("Inspector", "No data"))
            self.visualize_dataset_button.setEnabled(False)
            return
        message = f"dtype={page.dtype} · {page.values.shape[0]} × {page.values.shape[1]}"
        if page.warnings:
            message += " · " + "; ".join(page.warnings)
        self.data_message.setText(message)
        self.visualize_dataset_button.setEnabled(bool(page.values.size))
        self.data_table.resizeColumnsToContents()
        self.status_message.emit(tr("Inspector", "Page loaded"))

    def _export_dataset(self) -> None:
        """Выбрать формат и атомарно экспортировать текущий dataset."""
        if self._session is None or self._link is None:
            return
        npy_filter = tr("Inspector", "NumPy arrays (*.npy)")
        csv_filter = tr("Inspector", "CSV files (*.csv)")
        initial = self._session.original_path.with_name(
            f"{self._session.original_path.stem}-{self._link.name}.npy"
        )
        filename, selected_filter = QFileDialog.getSaveFileName(
            self,
            tr("Inspector", "Export dataset"),
            str(initial),
            f"{npy_filter};;{csv_filter}",
        )
        if not filename:
            return
        destination = Path(filename).expanduser().resolve()
        export_format = (
            ExportFormat.CSV
            if destination.suffix.casefold() == ".csv" or selected_filter == csv_filter
            else ExportFormat.NPY
        )
        expected_suffix = ".csv" if export_format is ExportFormat.CSV else ".npy"
        if not destination.suffix:
            destination = destination.with_suffix(expected_suffix)
        if destination in {
            self._session.active_path.resolve(),
            self._session.original_path.resolve(),
        }:
            self._show_error(tr("Inspector", "Export cannot replace an HDF5 document"))
            return
        selection = self._selection() if export_format is ExportFormat.CSV else None
        if export_format is ExportFormat.CSV and selection is None:
            return
        self._run_export(destination, export_format, selection)

    def _run_export(
        self,
        destination: Path,
        export_format: ExportFormat,
        selection: DatasetSlice | None,
    ) -> None:
        """Выполнить экспорт с прогрессом и возможностью безопасной отмены."""
        assert self._session is not None and self._link is not None
        progress = QProgressDialog(
            tr("Inspector", "Exporting dataset…"),
            tr("Inspector", "Cancel"),
            0,
            1000,
            self,
        )
        progress.setWindowTitle(tr("Inspector", "Dataset export"))
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.setAutoClose(False)

        def update(exported: int, total: int) -> None:
            fraction = 0 if total <= 0 else min(1000, int(exported * 1000 / total))
            progress.setValue(fraction)
            progress.setLabelText(
                tr("Inspector", "Exported {exported} of {total} elements").format(
                    exported=exported,
                    total=total,
                )
            )
            QApplication.processEvents()

        progress.show()
        try:
            report = export_hdf5_dataset(
                self._session.active_path,
                self._link.path,
                destination,
                DatasetExportOptions(export_format, selection=selection),
                progress=update,
                cancelled=progress.wasCanceled,
            )
        except H5ViewerError as exc:
            progress.close()
            self._show_error(str(exc))
            return
        progress.close()
        if report.cancelled:
            self.status_message.emit(tr("Inspector", "Export cancelled"))
            return
        self.status_message.emit(
            tr("Inspector", "Export completed: {path}").format(path=report.destination)
        )

    def _visualize_dataset(self) -> None:
        """Открыть line plot или heatmap для текущей ограниченной страницы."""
        if self._link is None:
            return
        page = self.dataset_model.page
        if page is None:
            return
        try:
            dialog = create_visualization_dialog(page.values, self._link.path, self)
        except VisualizationUnavailableError as exc:
            QMessageBox.information(
                self,
                tr("Dialog", "Information"),
                tr("Visualization", str(exc)),
            )
            return
        dialog.exec()

    def _populate_properties(self, details: ObjectDetails) -> None:
        properties = list(details.properties)
        report = self._group_size_report
        if report is not None and report.path == details.path:
            properties.extend(
                [
                    ("recursive_dataset_count", str(report.dataset_count)),
                    ("recursive_group_count", str(report.group_count)),
                    ("recursive_logical_bytes", str(report.logical_bytes)),
                    ("recursive_storage_bytes", str(report.storage_bytes)),
                    ("scanned_links", str(report.scanned_links)),
                    ("duplicate_objects", str(report.duplicate_objects)),
                    ("external_links_skipped", str(report.external_links_skipped)),
                    ("unresolved_links", str(report.unresolved_links)),
                    ("virtual_dataset_count", str(report.virtual_dataset_count)),
                ]
            )
        self.properties_table.setRowCount(len(properties))
        for row, (name, value) in enumerate(properties):
            label = tr("Property", _PROPERTY_LABELS.get(name, name))
            display_value = self._property_value(name, value)
            self.properties_table.setItem(row, 0, QTableWidgetItem(label))
            self.properties_table.setItem(row, 1, QTableWidgetItem(display_value))
        self.properties_table.resizeRowsToContents()

    @staticmethod
    def _property_value(name: str, value: str) -> str:
        """Привести размер или счётчик свойства к читаемому виду."""
        if name in _BYTE_PROPERTIES:
            try:
                return format_byte_size(int(value), exact=True)
            except ValueError:
                return value
        if name.endswith("_count") or name in {
            "size",
            "rank",
            "scanned_links",
            "duplicate_objects",
            "external_links_skipped",
            "unresolved_links",
        }:
            try:
                return f"{int(value):,}".replace(",", " ")
            except ValueError:
                return value
        return value

    def _calculate_group_size(self) -> None:
        """Выполнить отменяемый обход метаданных выбранной группы."""
        if (
            self._session is None
            or self._link is None
            or self._link.object_kind is not ObjectKind.GROUP
        ):
            return
        progress = QProgressDialog(
            tr("Inspector", "Calculating recursive group size…"),
            tr("Inspector", "Cancel"),
            0,
            0,
            self,
        )
        progress.setWindowTitle(tr("Inspector", "Group size"))
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.show()

        def update(count: int, path: str) -> None:
            progress.setLabelText(
                f"{tr('Inspector', 'Calculating recursive group size…')}\n{count}: {path}"
            )
            QApplication.processEvents()

        try:
            report = calculate_group_size(
                self._session.active_path,
                self._link.path,
                progress=update,
                cancelled=progress.wasCanceled,
            )
        except (H5ViewerError, ValueError) as exc:
            progress.close()
            self._show_error(str(exc))
            return
        progress.close()
        if report.cancelled:
            self.group_size_summary.setText(tr("Inspector", "Size calculation cancelled"))
            self.status_message.emit(tr("Inspector", "Size calculation cancelled"))
            return
        self._group_size_report = report
        if self._details is not None:
            self._populate_properties(self._details)
        self._update_group_size_summary()
        self.setCurrentWidget(self.properties_page)
        self.status_message.emit(tr("Inspector", "Group size calculated"))

    def _update_group_size_summary(self) -> None:
        """Показать результат или пояснение границ рекурсивного подсчёта."""
        if self._link is None or self._link.object_kind is not ObjectKind.GROUP:
            self.group_size_summary.clear()
            return
        report = self._group_size_report
        if report is None:
            self.group_size_summary.setText(
                tr(
                    "Inspector",
                    "The calculation counts unique dataset payloads; HDF5 metadata, attributes "
                    "and external links are not included.",
                )
            )
            return
        self.group_size_summary.setText(
            tr(
                "Inspector",
                "Datasets: {datasets} · Logical: {logical} · On disk: {storage}",
            ).format(
                datasets=report.dataset_count,
                logical=format_byte_size(report.logical_bytes),
                storage=format_byte_size(report.storage_bytes),
            )
        )

    def _populate_attributes(self, attributes: tuple[AttributeInfo, ...]) -> None:
        self.attributes_table.setRowCount(len(attributes))
        for row, attribute in enumerate(attributes):
            values = (attribute.name, attribute.dtype, str(attribute.shape), attribute.value_text)
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.ItemDataRole.UserRole, attribute)
                self.attributes_table.setItem(row, column, item)

    def _populate_link_info(self, link: LinkRef, details: ObjectDetails) -> None:
        lines = [
            f"{tr('Inspector', 'Path')}: {link.path}",
            f"{tr('Inspector', 'Link kind')}: {link.link_kind.value}",
            f"{tr('Inspector', 'Object token')}: {details.object_token or '—'}",
        ]
        if link.target_path:
            lines.append(f"{tr('Inspector', 'Target')}: {link.target_path}")
        if link.external_file:
            lines.append(f"{tr('Inspector', 'External file')}: {link.external_file}")
        if details.warnings:
            lines.extend(f"⚠ {warning}" for warning in details.warnings)
        self.link_summary.setPlainText("\n".join(lines))
        self._populate_references(details.references)
        self._populate_dimension_scales(details)
        self._populate_virtual_mappings(details)

    def _populate_references(self, references: tuple[ReferenceInfo, ...]) -> None:
        """Заполнить таблицу разрешённых и недоступных HDF5 references."""
        self.references_table.setRowCount(len(references))
        for row, reference in enumerate(references):
            source = self._reference_source_text(reference)
            target = reference.target_path or "—"
            details = self._reference_details_text(reference)
            values = (
                source,
                tr("Inspector", reference.reference_kind.value),
                target,
                details,
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.ItemDataRole.UserRole, reference)
                self.references_table.setItem(row, column, item)
        self.references_table.resizeColumnsToContents()
        self.references_table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.Stretch
        )
        self.open_reference_button.setEnabled(False)
        self._set_dataset_actions_enabled(False, False)

    def _reference_source_text(self, reference: ReferenceInfo) -> str:
        """Локализовать источник reference и сохранить точные координаты."""
        if reference.source_kind is ReferenceSourceKind.ATTRIBUTE:
            source = f"{tr('Inspector', 'Attribute')}: {reference.source_name}"
        else:
            source = tr("Inspector", "Dataset element")
        if reference.source_index is not None:
            source += f" {reference.source_index}"
        return source

    def _reference_details_text(self, reference: ReferenceInfo) -> str:
        """Собрать компактное описание region selection или ошибки."""
        parts: list[str] = []
        if reference.target_kind is not None:
            parts.append(tr("Inspector", reference.target_kind.value))
        if reference.selection_type is not None:
            parts.append(f"{tr('Inspector', 'Selection')}: {reference.selection_type}")
        if reference.selected_points is not None:
            parts.append(f"{tr('Inspector', 'Points')}: {reference.selected_points}")
        if reference.bounds is not None:
            parts.append(f"{tr('Inspector', 'Bounds')}: {reference.bounds}")
        if reference.error:
            error = (
                tr("Inspector", "Null reference")
                if reference.error == "Null reference"
                else reference.error
            )
            parts.append(f"{tr('Inspector', 'Error')}: {error}")
        return " · ".join(parts) or "—"

    def _populate_dimension_scales(self, details: ObjectDetails) -> None:
        """Показать labels и все шкалы каждой оси dataset."""
        scales = details.dimension_scales
        self.dimension_scales_table.setRowCount(len(scales))
        for row, dimension in enumerate(scales):
            values = (
                str(dimension.axis),
                dimension.label or "—",
                ", ".join(dimension.scale_paths) or "—",
            )
            for column, value in enumerate(values):
                self.dimension_scales_table.setItem(row, column, QTableWidgetItem(value))
        self.dimension_scales_table.resizeColumnsToContents()
        self.dimension_scales_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch
        )

    def _populate_virtual_mappings(self, details: ObjectDetails) -> None:
        """Показать структурированные соответствия VDS без payload."""
        mappings = details.virtual_mappings
        self.virtual_mappings_table.setRowCount(len(mappings))
        for row, mapping in enumerate(mappings):
            values = (
                mapping.source_file,
                mapping.source_dataset,
                mapping.source_selection,
                mapping.virtual_selection,
            )
            for column, value in enumerate(values):
                self.virtual_mappings_table.setItem(row, column, QTableWidgetItem(value))
        self.virtual_mappings_table.resizeColumnsToContents()
        self.virtual_mappings_table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.Stretch
        )

    def _selected_reference(self) -> ReferenceInfo | None:
        row = self.references_table.currentRow()
        if row < 0:
            return None
        item = self.references_table.item(row, 0)
        value = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        return value if isinstance(value, ReferenceInfo) else None

    def _reference_selection_changed(self) -> None:
        reference = self._selected_reference()
        self.open_reference_button.setEnabled(
            reference is not None and reference.target_path is not None
        )

    def _navigate_reference(self) -> None:
        """Попросить главное окно открыть доступную цель reference."""
        reference = self._selected_reference()
        if self._session is None or reference is None or reference.target_path is None:
            return
        self.reference_activated.emit(self._session, reference.target_path)

    def _populate_raw(self, details: ObjectDetails) -> None:
        lines = [f'{details.kind.value.upper()} "{details.path}" {{']
        for name, value in details.properties:
            lines.append(f"  {name.upper()} {value}")
        if details.attributes:
            lines.append("  ATTRIBUTES {")
            for attribute in details.attributes:
                lines.append(
                    f'    "{attribute.name}" {attribute.dtype} '
                    f"{attribute.shape} = {attribute.value_text}"
                )
            lines.append("  }")
        if details.references:
            lines.append("  REFERENCES {")
            for reference in details.references:
                lines.append(
                    f"    {reference.reference_kind.value} "
                    f"{reference.source_name}{reference.source_index or ''} "
                    f"-> {reference.target_path or reference.error or 'NULL'}"
                )
            lines.append("  }")
        if details.dimension_scales:
            lines.append("  DIMENSION_SCALES {")
            for dimension in details.dimension_scales:
                lines.append(
                    f"    AXIS {dimension.axis} LABEL {dimension.label!r} "
                    f"SCALES {dimension.scale_paths}"
                )
            lines.append("  }")
        if details.virtual_mappings:
            lines.append("  VIRTUAL_MAPPINGS {")
            for mapping in details.virtual_mappings:
                lines.append(
                    f"    {mapping.source_file}:{mapping.source_dataset} "
                    f"{mapping.source_selection} -> {mapping.virtual_selection}"
                )
            lines.append("  }")
        lines.append("}")
        self.raw_text.setPlainText("\n".join(lines))

    def _show_broken_link(self, link: LinkRef, error: str | None = None) -> None:
        self.dataset_model.clear()
        self.attributes_table.setRowCount(0)
        self.properties_table.setRowCount(0)
        self.references_table.setRowCount(0)
        self.dimension_scales_table.setRowCount(0)
        self.virtual_mappings_table.setRowCount(0)
        self.open_reference_button.setEnabled(False)
        message = error or link.error or tr("Inspector", "Broken link")
        link_lines = (
            link.path,
            link.link_kind.value,
            link.external_file or "",
            link.target_path or "",
            message,
        )
        self.link_summary.setPlainText("\n".join(link_lines))
        self.raw_text.setPlainText(message)
        self.preview_text.setPlainText(message)
        self.data_message.setText(message)
        self.setCurrentWidget(self.links_page)

    def _selected_attribute(self) -> AttributeInfo | None:
        row = self.attributes_table.currentRow()
        if row < 0:
            return None
        item = self.attributes_table.item(row, 0)
        value = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        return value if isinstance(value, AttributeInfo) else None

    def _add_attribute(self) -> None:
        if self._session is None or self._link is None or not self._ensure_editing(self._session):
            return
        name, accepted = QInputDialog.getText(
            self, tr("Inspector", "Add attribute"), tr("Inspector", "Attribute name")
        )
        if not accepted or not name:
            return
        value, accepted = QInputDialog.getMultiLineText(
            self,
            tr("Inspector", "Add attribute"),
            tr("Inspector", "Attribute value (text or JSON)"),
        )
        if not accepted:
            return
        self._execute_attribute(SetAttributeCommand(self._link.path, name, value))

    def _edit_attribute(self, _index: Any = None) -> None:
        attribute = self._selected_attribute()
        if (
            attribute is None
            or self._session is None
            or self._link is None
            or not self._ensure_editing(self._session)
        ):
            return
        if not attribute.editable:
            QMessageBox.information(
                self,
                tr("Dialog", "Unsupported edit"),
                tr("Inspector", "Attribute is read-only for this datatype"),
            )
            return
        value, accepted = QInputDialog.getMultiLineText(
            self,
            tr("Inspector", "Edit attribute"),
            tr("Inspector", "Attribute value (text or JSON)"),
            attribute.value_text,
        )
        if accepted:
            self._execute_attribute(SetAttributeCommand(self._link.path, attribute.name, value))

    def _delete_attribute(self) -> None:
        attribute = self._selected_attribute()
        if (
            attribute is None
            or self._session is None
            or self._link is None
            or not self._ensure_editing(self._session)
        ):
            return
        answer = QMessageBox.question(
            self,
            tr("Dialog", "Confirm"),
            tr("Inspector", "Delete selected attribute?"),
        )
        if answer is QMessageBox.StandardButton.Yes:
            self._execute_attribute(DeleteAttributeCommand(self._link.path, attribute.name))

    def _execute_attribute(self, command: Any) -> None:
        assert self._session is not None
        try:
            self._session.execute(command)
        except H5ViewerError as exc:
            self._show_error(str(exc))
            return
        self.refresh()
        self.content_changed.emit(self._session)

    def _data_changed(self) -> None:
        if self._session is not None:
            self.content_changed.emit(self._session)

    def _resize_dataset(self) -> None:
        """Изменить размер выбранного dataset обратимой командой."""
        if self._session is None or self._link is None:
            return
        try:
            extent = self._session.repository().dataset_extent(self._link.path)
        except H5ViewerError as exc:
            self._show_error(str(exc))
            return
        if extent.chunks is None:
            QMessageBox.information(
                self,
                tr("Dialog", "Unsupported edit"),
                tr("DatasetDialog", "Only chunked datasets can be resized"),
            )
            return
        dialog = ResizeDatasetDialog(extent, self)
        if dialog.exec() != ResizeDatasetDialog.DialogCode.Accepted:
            return
        new_shape = dialog.new_shape()
        if any(new < current for current, new in zip(extent.shape, new_shape, strict=True)):
            answer = QMessageBox.warning(
                self,
                tr("Dialog", "Confirm"),
                tr(
                    "DatasetDialog",
                    "Shrinking discards data outside the new shape. The undo snapshot may "
                    "require disk space equal to the working file. Continue?",
                ),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer is not QMessageBox.StandardButton.Yes:
                return
        if not self._ensure_editing(self._session):
            return
        try:
            self._session.execute(ResizeDatasetCommand(self._link.path, new_shape))
        except H5ViewerError as exc:
            self._show_error(str(exc))
            return
        try:
            self._link = self._session.repository().link(self._link.path)
        except H5ViewerError:
            self._link = replace(self._link, shape=new_shape)
        self.show_object(self._session, self._link)
        self.dataset_resized.emit(
            self._session,
            self._link.path,
            self._link.object_token,
            new_shape,
        )
        self.content_changed.emit(self._session)

    def _show_error(self, message: str) -> None:
        QMessageBox.critical(self, tr("Dialog", "Error"), message)
