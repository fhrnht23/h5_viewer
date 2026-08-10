"""Диалоги поиска метаданных и сравнения документов двух панелей."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from h5viewer.application.document import DocumentSession
from h5viewer.domain.errors import H5ViewerError
from h5viewer.domain.models import (
    ComparisonOptions,
    DifferenceKind,
    FileComparisonReport,
    FileDifference,
    MetadataMatch,
    MetadataSearchOptions,
    MetadataSearchReport,
)
from h5viewer.infrastructure.hdf5.analysis import compare_hdf5_files, search_hdf5_metadata
from h5viewer.presentation.qt.translations import tr


class MetadataSearchDialog(QDialog):
    """Ищет текст только в metadata и ограниченных значениях атрибутов."""

    path_activated = Signal(object, str)

    def __init__(self, session: DocumentSession, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._session = session
        self._report: MetadataSearchReport | None = None
        self._build_ui()
        self.retranslate_ui()
        self.resize(980, 620)

    @property
    def report(self) -> MetadataSearchReport | None:
        return self._report

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.file_value = QLabel(str(self._session.original_path), self)
        self.query_edit = QLineEdit(self)
        self.query_edit.setClearButtonEnabled(True)
        self.query_edit.returnPressed.connect(self.run_search)
        self.case_sensitive = QCheckBox(self)
        self.attribute_values = QCheckBox(self)
        self.attribute_values.setChecked(True)
        self.max_results = QSpinBox(self)
        self.max_results.setRange(10, 10_000)
        self.max_results.setValue(1000)
        self.max_results.setGroupSeparatorShown(True)
        self.file_label = QLabel(self)
        self.query_label = QLabel(self)
        self.max_results_label = QLabel(self)
        form.addRow(self.file_label, self.file_value)
        form.addRow(self.query_label, self.query_edit)
        options = QHBoxLayout()
        options.addWidget(self.case_sensitive)
        options.addWidget(self.attribute_values)
        options.addStretch(1)
        form.addRow(options)
        form.addRow(self.max_results_label, self.max_results)
        layout.addLayout(form)

        command_row = QHBoxLayout()
        self.search_button = QPushButton(self)
        self.search_button.clicked.connect(self.run_search)
        self.summary_label = QLabel(self)
        self.summary_label.setWordWrap(True)
        command_row.addWidget(self.search_button)
        command_row.addWidget(self.summary_label, 1)
        layout.addLayout(command_row)

        self.results_table = QTableWidget(0, 5, self)
        _configure_results_table(self.results_table)
        self.results_table.cellDoubleClicked.connect(self._open_result)
        layout.addWidget(self.results_table, 1)

        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

    def retranslate_ui(self) -> None:
        """Перевести статические подписи диалога."""
        self.setWindowTitle(tr("Analysis", "Metadata search"))
        self.file_label.setText(tr("Analysis", "File"))
        self.query_label.setText(tr("Analysis", "Search query"))
        self.query_edit.setPlaceholderText(tr("Analysis", "Text in paths and metadata…"))
        self.case_sensitive.setText(tr("Analysis", "Case-sensitive"))
        self.attribute_values.setText(tr("Analysis", "Search attribute values"))
        self.max_results_label.setText(tr("Analysis", "Maximum results"))
        self.search_button.setText(tr("Analysis", "Search"))
        self.results_table.setHorizontalHeaderLabels(
            [
                tr("Analysis", "Path"),
                tr("Analysis", "Object type"),
                tr("Analysis", "Match field"),
                tr("Analysis", "Name"),
                tr("Analysis", "Value"),
            ]
        )
        close_button = self.buttons.button(QDialogButtonBox.StandardButton.Close)
        if close_button is not None:
            close_button.setText(tr("Analysis", "Close"))

    def run_search(self) -> None:
        """Выполнить отменяемый поиск и заполнить таблицу результатов."""
        query = self.query_edit.text().strip()
        if not query:
            QMessageBox.information(
                self,
                tr("Dialog", "Information"),
                tr("Analysis", "Enter a search query"),
            )
            return
        progress = _progress_dialog(self, tr("Analysis", "Searching metadata…"))

        def update(count: int, path: str) -> None:
            progress.setLabelText(f"{tr('Analysis', 'Searching metadata…')}\n{count}: {path}")
            QApplication.processEvents()

        try:
            self._report = search_hdf5_metadata(
                self._session.active_path,
                MetadataSearchOptions(
                    query=query,
                    case_sensitive=self.case_sensitive.isChecked(),
                    include_attribute_values=self.attribute_values.isChecked(),
                    max_results=self.max_results.value(),
                ),
                progress=update,
                cancelled=progress.wasCanceled,
            )
        except (H5ViewerError, ValueError) as exc:
            progress.close()
            QMessageBox.critical(self, tr("Dialog", "Error"), str(exc))
            return
        progress.close()
        self._populate_results(self._report)

    def _populate_results(self, report: MetadataSearchReport) -> None:
        self.results_table.setRowCount(len(report.matches))
        for row, match in enumerate(report.matches):
            values = (
                match.path,
                tr("Analysis", match.object_kind.value),
                tr("Analysis", match.field.value),
                match.name,
                match.value_preview,
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.ItemDataRole.UserRole, match)
                self.results_table.setItem(row, column, item)
        self.results_table.resizeColumnsToContents()
        self.results_table.horizontalHeader().setSectionResizeMode(
            4, QHeaderView.ResizeMode.Stretch
        )
        status = (
            tr("Analysis", "Search cancelled")
            if report.cancelled
            else tr("Analysis", "Found: {count}").format(count=len(report.matches))
        )
        status += f" · {tr('Analysis', 'Scanned links')}: {report.scanned_links}"
        if report.truncated:
            status += f" · {tr('Analysis', 'Result limit reached')}"
        if report.warnings:
            status += f" · ⚠ {len(report.warnings)}"
        self.summary_label.setText(status)

    def _open_result(self, row: int, _column: int) -> None:
        item = self.results_table.item(row, 0)
        match = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        if isinstance(match, MetadataMatch):
            self.path_activated.emit(self._session, match.path)
            self.accept()


class FileComparisonDialog(QDialog):
    """Сравнивает документы левой и правой панелей блоками ограниченного размера."""

    path_activated = Signal(object, str)

    def __init__(
        self,
        left_session: DocumentSession,
        right_session: DocumentSession,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._left_session = left_session
        self._right_session = right_session
        self._report: FileComparisonReport | None = None
        self._build_ui()
        self.retranslate_ui()
        self.resize(1100, 680)

    @property
    def report(self) -> FileComparisonReport | None:
        return self._report

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.left_value = QLabel(str(self._left_session.original_path), self)
        self.right_value = QLabel(str(self._right_session.original_path), self)
        self.left_label = QLabel(self)
        self.right_label = QLabel(self)
        form.addRow(self.left_label, self.left_value)
        form.addRow(self.right_label, self.right_value)
        options = QHBoxLayout()
        self.compare_data = QCheckBox(self)
        self.compare_data.setChecked(True)
        self.absolute_tolerance = _tolerance_spinbox(self)
        self.relative_tolerance = _tolerance_spinbox(self)
        self.block_megabytes = QSpinBox(self)
        self.block_megabytes.setRange(1, 256)
        self.block_megabytes.setValue(4)
        self.maximum_differences = QSpinBox(self)
        self.maximum_differences.setRange(10, 100_000)
        self.maximum_differences.setValue(1000)
        self.absolute_label = QLabel(self)
        self.relative_label = QLabel(self)
        self.block_label = QLabel(self)
        self.maximum_label = QLabel(self)
        options.addWidget(self.compare_data)
        options.addWidget(self.absolute_label)
        options.addWidget(self.absolute_tolerance)
        options.addWidget(self.relative_label)
        options.addWidget(self.relative_tolerance)
        options.addWidget(self.block_label)
        options.addWidget(self.block_megabytes)
        options.addWidget(self.maximum_label)
        options.addWidget(self.maximum_differences)
        options.addStretch(1)
        form.addRow(options)
        layout.addLayout(form)

        command_row = QHBoxLayout()
        self.compare_button = QPushButton(self)
        self.compare_button.clicked.connect(self.run_comparison)
        self.summary_label = QLabel(self)
        self.summary_label.setWordWrap(True)
        command_row.addWidget(self.compare_button)
        command_row.addWidget(self.summary_label, 1)
        layout.addLayout(command_row)

        self.results_table = QTableWidget(0, 5, self)
        _configure_results_table(self.results_table)
        self.results_table.cellDoubleClicked.connect(self._open_result)
        layout.addWidget(self.results_table, 1)

        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

    def retranslate_ui(self) -> None:
        """Перевести статические подписи диалога сравнения."""
        self.setWindowTitle(tr("Analysis", "Compare pane documents"))
        self.left_label.setText(tr("Analysis", "Left file"))
        self.right_label.setText(tr("Analysis", "Right file"))
        self.compare_data.setText(tr("Analysis", "Compare dataset values"))
        self.absolute_label.setText(tr("Analysis", "Abs. tolerance"))
        self.relative_label.setText(tr("Analysis", "Rel. tolerance"))
        self.block_label.setText(tr("Analysis", "Block, MiB"))
        self.maximum_label.setText(tr("Analysis", "Maximum differences"))
        self.compare_button.setText(tr("Analysis", "Compare"))
        self.results_table.setHorizontalHeaderLabels(
            [
                tr("Analysis", "Path"),
                tr("Analysis", "Difference"),
                tr("Analysis", "Details"),
                tr("Analysis", "Left value"),
                tr("Analysis", "Right value"),
            ]
        )
        close_button = self.buttons.button(QDialogButtonBox.StandardButton.Close)
        if close_button is not None:
            close_button.setText(tr("Analysis", "Close"))

    def run_comparison(self) -> None:
        """Выполнить отменяемое сравнение и показать найденные различия."""
        progress = _progress_dialog(self, tr("Analysis", "Comparing files…"))

        def update(count: int, path: str) -> None:
            progress.setLabelText(f"{tr('Analysis', 'Comparing files…')}\n{count}: {path}")
            QApplication.processEvents()

        try:
            self._report = compare_hdf5_files(
                self._left_session.active_path,
                self._right_session.active_path,
                ComparisonOptions(
                    compare_data=self.compare_data.isChecked(),
                    relative_tolerance=self.relative_tolerance.value(),
                    absolute_tolerance=self.absolute_tolerance.value(),
                    max_differences=self.maximum_differences.value(),
                    block_bytes=self.block_megabytes.value() * 1024 * 1024,
                ),
                progress=update,
                cancelled=progress.wasCanceled,
            )
        except (H5ViewerError, ValueError) as exc:
            progress.close()
            QMessageBox.critical(self, tr("Dialog", "Error"), str(exc))
            return
        progress.close()
        self._populate_results(self._report)

    def _populate_results(self, report: FileComparisonReport) -> None:
        self.results_table.setRowCount(len(report.differences))
        for row, difference in enumerate(report.differences):
            values = (
                difference.path,
                tr("Analysis", difference.kind.value),
                tr("Analysis", difference.detail),
                difference.left_value,
                difference.right_value,
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.ItemDataRole.UserRole, difference)
                self.results_table.setItem(row, column, item)
        self.results_table.resizeColumnsToContents()
        self.results_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch
        )
        if report.cancelled:
            status = tr("Analysis", "Comparison cancelled")
        elif report.identical:
            status = tr("Analysis", "Files are identical for selected checks")
        else:
            status = tr("Analysis", "Differences: {count}").format(count=len(report.differences))
        status += (
            f" · {tr('Analysis', 'Objects')}: {report.compared_objects}"
            f" · {tr('Analysis', 'Datasets')}: {report.compared_datasets}"
            f" · {tr('Analysis', 'Elements')}: {report.compared_elements}"
        )
        if report.truncated:
            status += f" · {tr('Analysis', 'Result limit reached')}"
        if report.warnings:
            status += f" · ⚠ {len(report.warnings)}"
        self.summary_label.setText(status)

    def _open_result(self, row: int, _column: int) -> None:
        item = self.results_table.item(row, 0)
        difference = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        if not isinstance(difference, FileDifference):
            return
        session = (
            self._right_session
            if difference.kind is DifferenceKind.ONLY_RIGHT
            else self._left_session
        )
        self.path_activated.emit(session, difference.path)
        self.accept()


def _configure_results_table(table: QTableWidget) -> None:
    """Настроить единый read-only режим таблиц анализа."""
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setAlternatingRowColors(True)
    table.verticalHeader().hide()
    table.horizontalHeader().setStretchLastSection(True)


def _progress_dialog(parent: QWidget, label: str) -> QProgressDialog:
    """Создать немодальный индикатор с работающей кнопкой отмены."""
    progress = QProgressDialog(label, tr("Analysis", "Cancel"), 0, 0, parent)
    progress.setWindowTitle(tr("Analysis", "Analysis"))
    progress.setWindowModality(Qt.WindowModality.WindowModal)
    progress.setMinimumDuration(0)
    progress.setAutoClose(False)
    progress.show()
    return progress


def _tolerance_spinbox(parent: QWidget) -> QDoubleSpinBox:
    """Создать поле допуска с достаточной точностью для научных данных."""
    spinbox = QDoubleSpinBox(parent)
    spinbox.setRange(0.0, 1e100)
    spinbox.setDecimals(12)
    spinbox.setSingleStep(1e-6)
    spinbox.setStepType(QDoubleSpinBox.StepType.AdaptiveDecimalStepType)
    return spinbox
