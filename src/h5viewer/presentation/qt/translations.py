"""Локализация интерфейса через механизм переводчиков Qt."""

from __future__ import annotations

from PySide6.QtCore import QCoreApplication, QObject, QSettings, QTranslator, Signal
from PySide6.QtWidgets import QApplication

_RU: dict[str, str] = {
    "H5 Viewer": "H5 Viewer",
    "File": "Файл",
    "Edit": "Правка",
    "View": "Вид",
    "Language": "Язык",
    "Help": "Справка",
    "Open…": "Открыть…",
    "New file…": "Новый файл…",
    "Close file": "Закрыть файл",
    "Save": "Сохранить",
    "Save As…": "Сохранить как…",
    "Discard changes": "Отменить изменения",
    "Exit": "Выход",
    "Enable safe editing": "Включить безопасное редактирование",
    "Undo": "Отменить",
    "Redo": "Повторить",
    "Refresh": "Обновить",
    "Dark theme": "Тёмная тема",
    "Russian": "Русский",
    "English": "Английский",
    "About": "О программе",
    "No file open": "Файл не открыт",
    "Open an HDF5 file to begin": "Откройте HDF5-файл, чтобы начать работу",
    "Filter objects…": "Фильтр объектов…",
    "Path": "Путь",
    "Name": "Имя",
    "Type": "Тип",
    "Shape": "Форма",
    "Dtype": "Тип данных",
    "Storage": "Хранение",
    "Data": "Данные",
    "Attributes": "Атрибуты",
    "Properties": "Свойства",
    "Links / References": "Ссылки / References",
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
    "Rename…": "Переименовать…",
    "Group name": "Имя группы",
    "New name": "Новое имя",
    "Create group": "Создание группы",
    "Rename object": "Переименование объекта",
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
        if self._language == "ru":
            self._application.removeTranslator(self._translator)
        self._language = language
        if language == "ru":
            self._application.installTranslator(self._translator)
        self._settings.setValue("ui/language", language)
        self.language_changed.emit(language)
