"""Диалоги создания и изменения размера HDF5 datasets."""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from h5viewer.domain.models import DatasetCreationOptions, DatasetExtent
from h5viewer.presentation.qt.translations import tr


@dataclass(frozen=True, slots=True)
class DatasetCreationRequest:
    """Проверенный результат диалога создания dataset."""

    name: str
    options: DatasetCreationOptions


class DatasetCreationDialog(QDialog):
    """Собирает основные параметры хранения нового dataset."""

    def __init__(self, parent_path: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._parent_path = parent_path
        self._request: DatasetCreationRequest | None = None
        self.setWindowTitle(tr("DatasetDialog", "Create dataset"))
        self.setMinimumWidth(520)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"{tr('DatasetDialog', 'Parent group')}: {self._parent_path}"))
        form = QFormLayout()

        self.name_edit = QLineEdit(self)
        self.shape_edit = QLineEdit("100, 10", self)
        self.shape_edit.setPlaceholderText(tr("DatasetDialog", "Empty means scalar"))
        self.maxshape_edit = QLineEdit(self)
        self.maxshape_edit.setPlaceholderText(
            tr("DatasetDialog", "For example: *, 10; empty means fixed size")
        )

        self.dtype_combo = QComboBox(self)
        self.dtype_combo.setEditable(True)
        for specification in (
            "float64",
            "float32",
            "int64",
            "int32",
            "int16",
            "int8",
            "uint64",
            "uint32",
            "uint16",
            "uint8",
            "bool",
            "complex128",
            "S32",
            "utf-8",
        ):
            self.dtype_combo.addItem(specification, specification)

        self.layout_combo = QComboBox(self)
        self.layout_combo.addItem(tr("DatasetDialog", "Automatic"), None)
        self.layout_combo.addItem(tr("DatasetDialog", "Chunked"), True)
        self.layout_combo.addItem(tr("DatasetDialog", "Contiguous"), False)
        self.layout_combo.currentIndexChanged.connect(self._update_controls)

        self.chunks_edit = QLineEdit(self)
        self.chunks_edit.setPlaceholderText(tr("DatasetDialog", "Empty means automatic"))
        self.compression_combo = QComboBox(self)
        self.compression_combo.addItem(tr("DatasetDialog", "None"), None)
        self.compression_combo.addItem("gzip", "gzip")
        self.compression_combo.addItem("lzf", "lzf")
        self.compression_combo.currentIndexChanged.connect(self._update_controls)
        self.compression_level = QSpinBox(self)
        self.compression_level.setRange(0, 9)
        self.compression_level.setValue(4)
        self.fill_value_edit = QLineEdit(self)
        self.fill_value_edit.setPlaceholderText(tr("DatasetDialog", "Empty means dtype default"))
        self.shuffle_check = QCheckBox(tr("DatasetDialog", "Shuffle filter"), self)
        self.fletcher32_check = QCheckBox(tr("DatasetDialog", "Fletcher32 checksum"), self)

        form.addRow(tr("DatasetDialog", "Name"), self.name_edit)
        form.addRow(tr("DatasetDialog", "Shape"), self.shape_edit)
        form.addRow(tr("DatasetDialog", "Maximum shape"), self.maxshape_edit)
        form.addRow(tr("DatasetDialog", "Dtype"), self.dtype_combo)
        form.addRow(tr("DatasetDialog", "Layout"), self.layout_combo)
        form.addRow(tr("DatasetDialog", "Chunk shape"), self.chunks_edit)
        form.addRow(tr("DatasetDialog", "Compression"), self.compression_combo)
        form.addRow(tr("DatasetDialog", "Gzip level"), self.compression_level)
        form.addRow(tr("DatasetDialog", "Fill value"), self.fill_value_edit)
        form.addRow(self.shuffle_check)
        form.addRow(self.fletcher32_check)
        layout.addLayout(form)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        self.buttons.accepted.connect(self._validate_and_accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self._update_controls()

    def request(self) -> DatasetCreationRequest:
        """Вернуть проверенные параметры после успешного принятия диалога."""
        if self._request is None:
            self._request = self._make_request()
        return self._request

    def _validate_and_accept(self) -> None:
        try:
            self._request = self._make_request()
        except ValueError as exc:
            QMessageBox.warning(
                self,
                tr("Dialog", "Error"),
                tr("DatasetDialog", str(exc)),
            )
            return
        self.accept()

    def _make_request(self) -> DatasetCreationRequest:
        name = self.name_edit.text().strip()
        if not name or "/" in name or "\x00" in name:
            raise ValueError("Enter a valid dataset name")
        shape = cast(
            tuple[int, ...],
            _parse_dimensions(self.shape_edit.text(), allow_unlimited=False),
        )
        maxshape_text = self.maxshape_edit.text().strip()
        maxshape = _parse_dimensions(maxshape_text, allow_unlimited=True) if maxshape_text else None
        chunks_text = self.chunks_edit.text().strip()
        chunks = (
            cast(
                tuple[int, ...],
                _parse_dimensions(chunks_text, allow_unlimited=False),
            )
            if chunks_text
            else None
        )
        if maxshape is not None:
            if len(maxshape) != len(shape):
                raise ValueError("Shape and maximum shape must have the same rank")
            for size, maximum in zip(shape, maxshape, strict=True):
                if maximum is not None and maximum < size:
                    raise ValueError("Maximum shape cannot be smaller than shape")
        if chunks is not None and (
            len(chunks) != len(shape) or any(value <= 0 for value in chunks)
        ):
            raise ValueError("Chunk shape must contain one positive value per axis")

        chunked = cast(bool | None, self.layout_combo.currentData())
        compression = cast(str | None, self.compression_combo.currentData())
        requires_chunks = bool(
            maxshape is not None
            or chunks is not None
            or compression is not None
            or self.shuffle_check.isChecked()
            or self.fletcher32_check.isChecked()
        )
        if chunked is False and requires_chunks:
            raise ValueError("Contiguous layout cannot use chunks, compression or maximum shape")
        if not shape and (requires_chunks or chunked is True):
            raise ValueError("Scalar datasets cannot be chunked or compressed")

        fill_text = self.fill_value_edit.text()
        options = DatasetCreationOptions(
            shape=shape,
            dtype=self.dtype_combo.currentText().strip(),
            maxshape=maxshape,
            chunked=chunked,
            chunks=chunks,
            compression=compression,
            compression_level=(self.compression_level.value() if compression == "gzip" else None),
            fill_value_text=fill_text if fill_text else None,
            shuffle=self.shuffle_check.isChecked(),
            fletcher32=self.fletcher32_check.isChecked(),
        )
        if not options.dtype:
            raise ValueError("Enter a dtype")
        return DatasetCreationRequest(name, options)

    def _update_controls(self, _index: int = -1) -> None:
        contiguous = self.layout_combo.currentData() is False
        compression = self.compression_combo.currentData()
        self.chunks_edit.setEnabled(not contiguous)
        self.maxshape_edit.setEnabled(not contiguous)
        self.compression_combo.setEnabled(not contiguous)
        self.compression_level.setEnabled(not contiguous and compression == "gzip")
        self.shuffle_check.setEnabled(not contiguous)
        self.fletcher32_check.setEnabled(not contiguous)


class ResizeDatasetDialog(QDialog):
    """Запрашивает новый размер расширяемого dataset."""

    def __init__(self, extent: DatasetExtent, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._extent = extent
        self._new_shape: tuple[int, ...] | None = None
        self.setWindowTitle(tr("DatasetDialog", "Resize dataset"))
        self.setMinimumWidth(460)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.addRow(tr("DatasetDialog", "Current shape"), QLabel(_format_dimensions(extent.shape)))
        form.addRow(
            tr("DatasetDialog", "Maximum shape"), QLabel(_format_dimensions(extent.maxshape))
        )
        self.shape_edit = QLineEdit(_format_dimensions(extent.shape), self)
        form.addRow(tr("DatasetDialog", "New shape"), self.shape_edit)
        layout.addLayout(form)
        notice = QLabel(
            tr(
                "DatasetDialog",
                "Only expansion is allowed; shrinking could irreversibly discard data.",
            ),
            self,
        )
        notice.setWordWrap(True)
        layout.addWidget(notice)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        self.buttons.accepted.connect(self._validate_and_accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

    def new_shape(self) -> tuple[int, ...]:
        """Вернуть проверенную новую форму dataset."""
        if self._new_shape is None:
            self._new_shape = self._parse_new_shape()
        return self._new_shape

    def _validate_and_accept(self) -> None:
        try:
            self._new_shape = self._parse_new_shape()
        except ValueError as exc:
            QMessageBox.warning(
                self,
                tr("Dialog", "Error"),
                tr("DatasetDialog", str(exc)),
            )
            return
        self.accept()

    def _parse_new_shape(self) -> tuple[int, ...]:
        shape = _parse_dimensions(self.shape_edit.text(), allow_unlimited=False)
        new_shape = cast(tuple[int, ...], shape)
        if self._extent.chunks is None:
            raise ValueError("Only chunked datasets can be resized")
        if len(new_shape) != len(self._extent.shape):
            raise ValueError("The new shape must have the same rank")
        if new_shape == self._extent.shape:
            raise ValueError("Enter a shape different from the current shape")
        if any(new < current for current, new in zip(self._extent.shape, new_shape, strict=True)):
            raise ValueError("Shrinking datasets is not supported")
        for value, maximum in zip(new_shape, self._extent.maxshape, strict=True):
            if maximum is not None and value > maximum:
                raise ValueError("The new shape exceeds maximum shape")
        return new_shape


def _parse_dimensions(text: str, *, allow_unlimited: bool) -> tuple[int | None, ...]:
    """Разобрать список размеров, разрешая `*` только для maxshape."""
    stripped = text.strip()
    if not stripped:
        return ()
    dimensions: list[int | None] = []
    for token in stripped.split(","):
        value = token.strip()
        if allow_unlimited and value.lower() in {"*", "none", "inf", "∞"}:
            dimensions.append(None)
            continue
        try:
            parsed = int(value)
        except ValueError as exc:
            raise ValueError(
                "Dimensions must be non-negative integers separated by commas"
            ) from exc
        if parsed < 0:
            raise ValueError("Dimensions must be non-negative integers separated by commas")
        dimensions.append(parsed)
    return tuple(dimensions)


def _format_dimensions(dimensions: tuple[int | None, ...]) -> str:
    """Подготовить форму для компактного редактируемого поля."""
    if not dimensions:
        return tr("DatasetDialog", "scalar")
    return ", ".join("*" if value is None else str(value) for value in dimensions)
