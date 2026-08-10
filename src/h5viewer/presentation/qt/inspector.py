"""Инспектор выбранного объекта HDF5."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
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
    DatasetSlice,
    LinkRef,
    ObjectDetails,
    ObjectKind,
    default_dataset_slice,
)
from h5viewer.presentation.qt.dialogs import ResizeDatasetDialog
from h5viewer.presentation.qt.models import DatasetTableModel
from h5viewer.presentation.qt.translations import tr

EnsureEditing = Callable[[DocumentSession], bool]


class ObjectInspector(QTabWidget):
    """Показывает свойства, атрибуты и ограниченный срез dataset."""

    content_changed = Signal(object)
    dataset_resized = Signal(object, str, object, object)
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

        self.properties_table = QTableWidget(0, 2, self)
        self.properties_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.properties_table.verticalHeader().hide()
        self.properties_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self.properties_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )

        self.links_text = QTextEdit(self)
        self.links_text.setReadOnly(True)
        self.preview_text = QTextEdit(self)
        self.preview_text.setReadOnly(True)
        self.raw_text = QTextEdit(self)
        self.raw_text.setReadOnly(True)
        self.raw_text.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)

        self.addTab(self.data_page, "")
        self.addTab(self.attributes_page, "")
        self.addTab(self.properties_table, "")
        self.addTab(self.links_text, "")
        self.addTab(self.preview_text, "")
        self.addTab(self.raw_text, "")

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
        self.add_attribute_button.setText(tr("Inspector", "Add"))
        self.edit_attribute_button.setText(tr("Inspector", "Change"))
        self.delete_attribute_button.setText(tr("Inspector", "Delete"))
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

    def clear_inspector(self) -> None:
        """Очистить содержимое при закрытии последнего документа."""
        self._session = None
        self._link = None
        self._details = None
        self._dataset_shape = None
        self.dataset_model.clear()
        self.attributes_table.setRowCount(0)
        self.properties_table.setRowCount(0)
        self.links_text.clear()
        self.preview_text.setPlainText(tr("Inspector", "Select an object to inspect it"))
        self.raw_text.clear()
        self.data_message.setText(tr("Inspector", "Select a dataset"))
        self._set_dataset_controls_enabled(False)

    def show_object(self, session: DocumentSession, link: LinkRef) -> None:
        """Показать выбранную ссылку и, если возможно, её целевой объект."""
        self._session = session
        self._link = link
        self._dataset_shape = link.shape
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
            self.resize_dataset_button.setEnabled(bool(link.shape))
            self._configure_dataset(link.shape)
            self._load_dataset_page()
            self.setCurrentWidget(self.data_page)
        elif link.object_kind is ObjectKind.DATASET:
            self._set_dataset_controls_enabled(False)
            self.dataset_model.clear()
            self.data_message.setText(tr("Inspector", "No data"))
        else:
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
        self.dataset_model.load(self._session, self._link.path, selection)
        if self.dataset_model.error:
            self.data_message.setText(self.dataset_model.error)
            return
        page = self.dataset_model.page
        if page is None:
            self.data_message.setText(tr("Inspector", "No data"))
            return
        message = f"dtype={page.dtype} · {page.values.shape[0]} × {page.values.shape[1]}"
        if page.warnings:
            message += " · " + "; ".join(page.warnings)
        self.data_message.setText(message)
        self.data_table.resizeColumnsToContents()
        self.status_message.emit(tr("Inspector", "Page loaded"))

    def _populate_properties(self, details: ObjectDetails) -> None:
        self.properties_table.setRowCount(len(details.properties))
        for row, (name, value) in enumerate(details.properties):
            self.properties_table.setItem(row, 0, QTableWidgetItem(name))
            self.properties_table.setItem(row, 1, QTableWidgetItem(value))

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
        self.links_text.setPlainText("\n".join(lines))

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
        lines.append("}")
        self.raw_text.setPlainText("\n".join(lines))

    def _show_broken_link(self, link: LinkRef, error: str | None = None) -> None:
        self.dataset_model.clear()
        self.attributes_table.setRowCount(0)
        self.properties_table.setRowCount(0)
        message = error or link.error or tr("Inspector", "Broken link")
        link_lines = (
            link.path,
            link.link_kind.value,
            link.external_file or "",
            link.target_path or "",
            message,
        )
        self.links_text.setPlainText("\n".join(link_lines))
        self.raw_text.setPlainText(message)
        self.preview_text.setPlainText(message)
        self.data_message.setText(message)
        self.setCurrentWidget(self.links_text)

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
        """Расширить выбранный dataset обратимой командой."""
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
        if all(
            maximum is not None and maximum <= current
            for current, maximum in zip(extent.shape, extent.maxshape, strict=True)
        ):
            QMessageBox.information(
                self,
                tr("Dialog", "Unsupported edit"),
                tr("DatasetDialog", "Dataset has no expandable axes"),
            )
            return
        dialog = ResizeDatasetDialog(extent, self)
        if dialog.exec() != ResizeDatasetDialog.DialogCode.Accepted:
            return
        new_shape = dialog.new_shape()
        if not self._ensure_editing(self._session):
            return
        try:
            self._session.execute(ResizeDatasetCommand(self._link.path, new_shape))
        except H5ViewerError as exc:
            self._show_error(str(exc))
            return
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
