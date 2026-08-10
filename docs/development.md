# Разработка

## Окружение

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
```

PySide6 6.11.1 не обнаруживал platform plugins в проверенной среде macOS 26 / Python 3.10,
поэтому проект временно ограничен совместимой веткой 6.10.x. Ограничение можно пересмотреть после
проверки следующего исправленного wheel.

## Команды

```bash
ruff format .
ruff check .
mypy src/h5viewer
QT_QPA_PLATFORM=offscreen pytest
h5viewer
```

На macOS и Linux `QT_QPA_PLATFORM=offscreen` используется только для GUI-тестов. Обычный запуск не
требует этой переменной.

## Правила

- Комментарии и docstrings пишутся на русском языке.
- Сообщения Git-коммитов пишутся на русском языке.
- Python identifiers остаются английскими.
- Тесты создают HDF5 fixtures программно во временном каталоге.
- Нельзя использовать реальные пользовательские файлы для destructive tests.

