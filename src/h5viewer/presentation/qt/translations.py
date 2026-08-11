"""Локализация интерфейса через механизм переводчиков Qt."""

from __future__ import annotations

import weakref
from typing import ClassVar

from PySide6.QtCore import QCoreApplication, QObject, QSettings, QTranslator, Signal
from PySide6.QtWidgets import QApplication

_RU: dict[str, str] = {
    "H5 Viewer": "H5 Viewer",
    "OK": "ОК",
    "&OK": "ОК",
    "Cancel": "Отмена",
    "&Cancel": "Отмена",
    "Yes": "Да",
    "&Yes": "Да",
    "No": "Нет",
    "&No": "Нет",
    "New": "Новый",
    "Open": "Открыть",
    "Edit mode": "Правка",
    "Discard": "Отменить",
    "File": "Файл",
    "Edit": "Правка",
    "View": "Вид",
    "Tools": "Инструменты",
    "Language": "Язык",
    "Help": "Справка",
    "Open…": "Открыть…",
    "Open inspector": "Открыть инспектор",
    "Object inspector": "Инспектор объекта",
    "Enter: open inspector": "Enter: открыть инспектор",
    "Enter: open group": "Enter: открыть группу",
    "New file…": "Новый файл…",
    "Close file": "Закрыть файл",
    "Save": "Сохранить",
    "Save As…": "Сохранить как…",
    "Discard changes": "Отменить изменения",
    "Exit": "Выход",
    "Enable safe editing": "Включить безопасное редактирование",
    "View object": "Просмотреть объект",
    "Undo": "Отменить",
    "Redo": "Повторить",
    "Refresh": "Обновить",
    "Search metadata…": "Поиск по метаданным…",
    "Compare panes…": "Сравнить панели…",
    "Copy to other pane": "Копировать в соседнюю панель",
    "Move to other pane": "Переместить в соседнюю панель",
    "Create group in active pane": "Создать группу в активной панели",
    "Create group in other pane": "Создать группу в соседней панели",
    "Rename selected object": "Переименовать выбранный объект",
    "Delete selected object": "Удалить выбранный объект",
    "Switch active pane": "Переключить активную панель",
    "Tree / folder view": "Дерево / папки",
    "Copy →": "Копировать →",
    "← Copy": "← Копировать",
    "Move →": "Переместить →",
    "← Move": "← Переместить",
    "Dark theme": "Тёмная тема",
    "Settings…": "Настройки…",
    "Settings": "Настройки",
    "Appearance": "Оформление",
    "Keyboard shortcuts": "Горячие клавиши",
    "Action": "Действие",
    "Shortcut": "Сочетание клавиш",
    "Total Commander-compatible shortcuts are used where the actions match.": (
        "Для совпадающих действий используются сочетания клавиш Total Commander."
    ),
    "Enter group or open inspector": "Войти в группу или открыть инспектор",
    "Appearance settings…": "Настройки оформления…",
    "Appearance settings": "Настройки оформления",
    "Choose a color scheme and a Qt widget style. Changes are applied immediately.": (
        "Выберите цветовую схему и стиль элементов Qt. Изменения применяются сразу."
    ),
    "Color scheme": "Цветовая схема",
    "Light": "Светлая",
    "Dark": "Тёмная",
    "Qt widget style": "Стиль элементов Qt",
    "Progress preview": "Предпросмотр индикатора",
    "Processing HDF5 objects…": "Обработка объектов HDF5…",
    "Cancel restores the previous appearance.": ("Кнопка «Отмена» вернёт предыдущее оформление."),
    "Russian": "Русский",
    "English": "Английский",
    "About": "О программе",
    "No file open": "Файл не открыт",
    "Open an HDF5 file to begin": "Откройте HDF5-файл, чтобы начать работу",
    "Filter objects…": "Фильтр объектов…",
    "Tree view": "Дерево",
    "Folder view": "Папки",
    "Go to parent group": "На уровень вверх",
    "Go to root group": "В корневую группу",
    "Path": "Путь",
    "Name": "Имя",
    "Type": "Тип",
    "Shape": "Форма",
    "Dtype": "Тип данных",
    "Storage": "Хранение",
    "Data": "Данные",
    "Attributes": "Атрибуты",
    "Properties": "Свойства",
    "Links / References": "Именованные ссылки / указатели",
    "Preview": "Предпросмотр",
    "Raw / DDL": "Raw / DDL",
    "Property": "Свойство",
    "Value": "Значение",
    "Add": "Добавить",
    "Change": "Изменить",
    "Delete": "Удалить",
    "Row axis": "Ось строк",
    "Column axis": "Ось столбцов",
    "Fixed indices": "Фиксированные индексы",
    "Row offset": "Смещение строк",
    "Column offset": "Смещение столбцов",
    "Load page": "Загрузить страницу",
    "Select a dataset": "Выберите набор данных",
    "Select an object to inspect it": "Выберите объект для просмотра",
    "No preview is available for this object": "Для этого объекта нет предпросмотра",
    "Link kind": "Тип ссылки",
    "Target": "Цель",
    "External file": "Внешний файл",
    "Object token": "Идентификатор объекта",
    "Metadata search": "Поиск по метаданным",
    "Search query": "Поисковый запрос",
    "Text in paths and metadata…": "Текст в путях и метаданных…",
    "Case-sensitive": "Учитывать регистр",
    "Search attribute values": "Искать в значениях атрибутов",
    "Maximum results": "Максимум результатов",
    "Search": "Найти",
    "Object type": "Тип объекта",
    "Match field": "Поле совпадения",
    "Close": "Закрыть",
    "Enter a search query": "Введите поисковый запрос",
    "Searching metadata…": "Поиск по метаданным…",
    "Search cancelled": "Поиск отменён",
    "Found: {count}": "Найдено: {count}",
    "Scanned links": "Проверено ссылок",
    "Result limit reached": "Достигнут лимит результатов",
    "Compare pane documents": "Сравнение документов панелей",
    "Left file": "Левый файл",
    "Right file": "Правый файл",
    "Compare dataset values": "Сравнивать значения наборов данных",
    "Abs. tolerance": "Абс. допуск",
    "Rel. tolerance": "Отн. допуск",
    "Block, MiB": "Блок, МиБ",
    "Maximum differences": "Максимум различий",
    "Compare": "Сравнить",
    "Difference": "Различие",
    "Left value": "Значение слева",
    "Right value": "Значение справа",
    "Comparing files…": "Сравнение файлов…",
    "Comparison cancelled": "Сравнение отменено",
    "Files are identical for selected checks": "Файлы совпадают по выбранным проверкам",
    "Differences: {count}": "Различий: {count}",
    "Datasets": "Наборы данных",
    "Elements": "Элементы",
    "Analysis": "Анализ",
    "path": "путь",
    "object_kind": "тип объекта",
    "link_kind": "тип ссылки",
    "dataset_metadata": "метаданные набора данных",
    "attribute_name": "имя атрибута",
    "attribute_value": "значение атрибута",
    "only_left": "только слева",
    "only_right": "только справа",
    "link": "ссылка",
    "metadata": "метаданные",
    "attribute": "атрибут",
    "data": "данные",
    "error": "ошибка",
    "Link": "Ссылка",
    "Object kind": "Тип объекта",
    "Dataset read": "Чтение набора данных",
    "References": "Указатели",
    "Dimension scales": "Шкалы измерений",
    "VDS mappings": "Соответствия VDS",
    "Source": "Источник",
    "Kind": "Вид",
    "Details": "Подробности",
    "Axis": "Ось",
    "Label": "Метка",
    "Attached scales": "Прикреплённые шкалы",
    "Source file": "Исходный файл",
    "Source dataset": "Исходный набор данных",
    "Source selection": "Исходная выборка",
    "Virtual selection": "Виртуальная выборка",
    "Go to target": "Перейти к цели",
    "Attribute": "Атрибут",
    "Dataset element": "Элемент набора данных",
    "Selection": "Выборка",
    "Points": "Точек",
    "Bounds": "Границы",
    "Null reference": "Пустой указатель",
    "object": "объект",
    "region": "область",
    "Warning": "Предупреждение",
    "Error": "Ошибка",
    "Information": "Информация",
    "Confirm": "Подтверждение",
    "Safe editing": "Безопасное редактирование",
    "A working copy will be created next to the original file. Continue?": (
        "Рядом с исходным файлом будет создана рабочая копия. Продолжить?"
    ),
    "Working copy created": "Рабочая копия создана",
    "Read-only": "Только чтение",
    "Editing": "Редактирование",
    "Modified": "Изменён",
    "Saved successfully": "Файл успешно сохранён",
    "Backup": "Резервная копия",
    "Discard all changes in this file?": "Отменить все изменения в этом файле?",
    "Changes discarded": "Изменения отменены",
    "The file has unsaved changes.": "В файле есть несохранённые изменения.",
    "Save changes before closing?": "Сохранить изменения перед закрытием?",
    "Create group…": "Создать группу…",
    "Create dataset…": "Создать набор данных…",
    "Create link…": "Создать ссылку…",
    "Rename…": "Переименовать…",
    "Move to…": "Переместить в…",
    "Delete…": "Удалить…",
    "Group name": "Имя группы",
    "New name": "Новое имя",
    "Create group": "Создание группы",
    "Create dataset": "Создание набора данных",
    "Rename object": "Переименование объекта",
    "Copy object": "Копирование объекта",
    "Destination name": "Имя в назначении",
    "Select a source object and a destination document": (
        "Выберите исходный объект и документ назначения"
    ),
    "The root group cannot be copied": "Корневую группу нельзя копировать",
    "Save or discard changes in the source file before copying it to another file": (
        "Сохраните или отмените изменения исходного файла перед копированием в другой файл"
    ),
    "The object will be copied without expanding soft/external links or references. Continue?": (
        "Объект будет скопирован без раскрытия soft/external links и references. Продолжить?"
    ),
    "Object copied": "Объект скопирован",
    "The root group cannot be moved": "Корневую группу нельзя перемещать",
    "Move object": "Перемещение объекта",
    "Object moved": "Объект перемещён",
    (
        "Moving between files changes two independent working copies and cannot be saved "
        "atomically. Save the destination first, then the source, or discard both. Continue?"
    ): (
        "Перемещение между файлами изменяет две независимые рабочие копии и не может быть "
        "сохранено атомарно. Сначала сохраните назначение, затем источник, либо отмените оба. "
        "Продолжить?"
    ),
    "Object moved; save destination, then source": (
        "Объект перемещён; сохраните назначение, затем источник"
    ),
    "Move undone": "Перемещение отменено",
    "Move repeated": "Перемещение повторено",
    "Destination HDF5 path": "Путь назначения HDF5",
    "Delete the selected link and its unreferenced object?": (
        "Удалить выбранную ссылку и объект, если на него больше нет ссылок?"
    ),
    "Create link": "Создание ссылки",
    "Hard link": "Жёсткая ссылка",
    "Soft link": "Мягкая ссылка",
    "External link": "Внешняя ссылка",
    "Browse…": "Обзор…",
    "Link type": "Тип ссылки",
    "Target HDF5 path": "Целевой путь HDF5",
    "Enter a valid link name": "Введите корректное имя ссылки",
    "Enter a target HDF5 path": "Введите целевой путь HDF5",
    "Select an external HDF5 file": "Выберите внешний файл HDF5",
    "Select external HDF5 file": "Выбор внешнего файла HDF5",
    "Resize…": "Изменить размер…",
    "Export…": "Экспорт…",
    "Visualize…": "Визуализация…",
    "NumPy arrays (*.npy)": "Массивы NumPy (*.npy)",
    "CSV files (*.csv)": "Файлы CSV (*.csv)",
    "Export dataset": "Экспорт набора данных",
    "Export cannot replace an HDF5 document": ("Экспорт не может заменить открытый HDF5-документ"),
    "Exporting dataset…": "Экспорт набора данных…",
    "Dataset export": "Экспорт набора данных",
    "Exported {exported} of {total} elements": ("Экспортировано элементов: {exported} из {total}"),
    "Export cancelled": "Экспорт отменён",
    "Export completed: {path}": "Экспорт завершён: {path}",
    "Dataset visualization": "Визуализация набора данных",
    "Current page: {shape}": "Текущая страница: {shape}",
    "Magnitude of complex values": "Модуль комплексных значений",
    "Dataset page is empty": "Страница набора данных пуста",
    "Only numeric dataset pages can be visualized": (
        "Визуализация доступна только для числовых наборов данных"
    ),
    "Visualization expects a one- or two-dimensional page": (
        "Для визуализации нужна одномерная или двумерная страница"
    ),
    "pyqtgraph is not installed; install the 'plots' extra": (
        "Модуль pyqtgraph не установлен; установите дополнение 'plots'"
    ),
    "Resize dataset": "Изменение размера набора данных",
    "Parent group": "Родительская группа",
    "Empty means scalar": "Пустое поле означает скаляр",
    "For example: *, 10; empty means fixed size": (
        "Например: *, 10; пустое поле означает фиксированный размер"
    ),
    "Automatic": "Автоматически",
    "Chunked": "Блочное",
    "Contiguous": "Непрерывное",
    "None": "Нет",
    "Empty means automatic": "Пустое поле означает автоматический выбор",
    "Empty means dtype default": "Пустое поле означает значение по умолчанию для dtype",
    "Shuffle filter": "Фильтр shuffle",
    "Fletcher32 checksum": "Контрольная сумма Fletcher32",
    "Maximum shape": "Максимальная форма",
    "Layout": "Размещение",
    "Chunk shape": "Форма блока",
    "Compression": "Сжатие",
    "Gzip level": "Уровень gzip",
    "Fill value": "Значение заполнения",
    "Current shape": "Текущая форма",
    "New shape": "Новая форма",
    "Shrinking discards data immediately; a full disk snapshot is created for undo.": (
        "Уменьшение сразу удаляет данные; для отмены создаётся полный дисковый снимок."
    ),
    "Enter a valid dataset name": "Введите корректное имя набора данных",
    "Shape and maximum shape must have the same rank": (
        "Форма и максимальная форма должны иметь одинаковый ранг"
    ),
    "Maximum shape cannot be smaller than shape": (
        "Максимальная форма не может быть меньше начальной"
    ),
    "Chunk shape must contain one positive value per axis": (
        "Форма блока должна содержать по одному положительному значению на ось"
    ),
    "Contiguous layout cannot use chunks, compression or maximum shape": (
        "Непрерывное размещение несовместимо с блоками, сжатием и максимальной формой"
    ),
    "Scalar datasets cannot be chunked or compressed": (
        "Скалярные наборы данных нельзя разбивать на блоки или сжимать"
    ),
    "Enter a dtype": "Укажите dtype",
    "Only chunked datasets can be resized": (
        "Изменять размер можно только у блочных наборов данных"
    ),
    "The new shape must have the same rank": "Новая форма должна иметь тот же ранг",
    "Enter a shape different from the current shape": ("Введите форму, отличающуюся от текущей"),
    (
        "Shrinking discards data outside the new shape. The undo snapshot may require disk "
        "space equal to the working file. Continue?"
    ): (
        "Уменьшение удалит данные за пределами новой формы. Снимку для отмены может потребоваться "
        "столько же места, сколько занимает рабочий файл. Продолжить?"
    ),
    "The new shape exceeds maximum shape": "Новая форма превышает максимальную",
    "Dimensions must be non-negative integers separated by commas": (
        "Размеры должны быть неотрицательными целыми числами через запятую"
    ),
    "scalar": "скаляр",
    "Attribute name": "Имя атрибута",
    "Attribute value (text or JSON)": "Значение атрибута (текст или JSON)",
    "Add attribute": "Добавление атрибута",
    "Edit attribute": "Изменение атрибута",
    "Delete selected attribute?": "Удалить выбранный атрибут?",
    "Unsupported edit": "Неподдерживаемое изменение",
    "File changed outside the application": "Файл изменён вне приложения",
    "Open HDF5 files": "Открытие HDF5-файлов",
    "Create HDF5 file": "Создание HDF5-файла",
    "Save HDF5 file as": "Сохранение HDF5-файла",
    "HDF5 files (*.h5 *.hdf5 *.he5);;All files (*)": (
        "Файлы HDF5 (*.h5 *.hdf5 *.he5);;Все файлы (*)"
    ),
    "The destination already exists. It will be replaced after a backup is created. Continue?": (
        "Файл назначения уже существует. После создания резервной копии "
        "он будет заменён. Продолжить?"
    ),
    "About H5 Viewer": "О программе H5 Viewer",
    "Cross-platform two-pane HDF5 viewer and safe editor.": (
        "Кроссплатформенный двухпанельный просмотрщик и безопасный редактор HDF5."
    ),
    "Ready": "Готово",
    "Plugins failed to load: {count}": "Не удалось загрузить плагинов: {count}",
    "Objects": "Объекты",
    "Cycle": "Цикл",
    "Broken link": "Повреждённая ссылка",
    "group": "группа",
    "dataset": "набор данных",
    "named_datatype": "именованный тип",
    "broken_link": "неразрешённая ссылка",
    "unknown": "неизвестно",
    "hard": "жёсткая",
    "soft": "мягкая",
    "external": "внешняя",
    "root": "корень",
    "user_defined": "пользовательская",
    "Attribute is read-only for this datatype": "Атрибут этого типа доступен только для чтения",
    "Dataset is read-only for this datatype": "Набор данных этого типа доступен только для чтения",
    "Invalid fixed indices": "Некорректные фиксированные индексы",
    "Page loaded": "Страница загружена",
    "Reference target opened": "Цель указателя открыта",
    "No data": "Нет данных",
    "Language changed": "Язык изменён",
}


def tr(context: str, source: str) -> str:
    """Перевести строку в указанном контексте."""
    return QCoreApplication.translate(context, source)


class DictionaryTranslator(QTranslator):
    """Небольшой встроенный переводчик без зависимости от `lrelease`."""

    def translate(
        self,
        context: str,
        source_text: str,
        disambiguation: str | None = None,
        n: int = -1,
    ) -> str:
        del context, disambiguation, n
        return _RU.get(source_text, source_text)


class LanguageManager(QObject):
    """Управляет текущим языком и сохраняет выбор пользователя."""

    language_changed = Signal(str)
    _active_manager: ClassVar[weakref.ReferenceType[LanguageManager] | None] = None

    def __init__(self, application: QApplication) -> None:
        super().__init__()
        self._application = application
        self._settings = QSettings()
        self._translator = DictionaryTranslator(self)
        self._language = "en"

    @property
    def language(self) -> str:
        return self._language

    def load(self) -> None:
        """Загрузить язык; при первом запуске выбрать русский."""
        language = str(self._settings.value("ui/language", "ru"))
        self.set_language(language if language in {"ru", "en"} else "ru")

    def set_language(self, language: str) -> None:
        """Установить язык и уведомить виджеты о необходимости обновить текст."""
        language = language if language in {"ru", "en"} else "ru"
        previous = self._active_manager() if self._active_manager is not None else None
        if previous is not None and previous is not self and previous._language == "ru":
            self._application.removeTranslator(previous._translator)
        if self._language == "ru":
            self._application.removeTranslator(self._translator)
        self._language = language
        if language == "ru":
            self._application.installTranslator(self._translator)
        self.__class__._active_manager = weakref.ref(self)
        self._settings.setValue("ui/language", language)
        self.language_changed.emit(language)
