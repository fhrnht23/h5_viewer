"""Доменные исключения, обрабатываемые слоем представления."""

from __future__ import annotations


class H5ViewerError(Exception):
    """Базовый класс ожидаемых ошибок приложения."""


class FileOpenError(H5ViewerError):
    """Файл не является доступным для чтения HDF5-файлом."""


class ObjectNotFoundError(H5ViewerError):
    """Путь HDF5 больше не разрешается в объект."""


class UnsupportedEditError(H5ViewerError):
    """Изменение нельзя выполнить без риска потери исходного типа HDF5."""


class ValidationError(H5ViewerError):
    """Рабочий файл не прошёл проверку целостности."""


class SaveConflictError(H5ViewerError):
    """Исходный файл был изменён вне приложения."""


class InsufficientSpaceError(H5ViewerError):
    """На диске недостаточно места для безопасной рабочей копии."""
