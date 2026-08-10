# H5 Viewer

H5 Viewer — кроссплатформенное двухпанельное desktop-приложение для просмотра и безопасного
редактирования файлов HDF5. Интерфейс поддерживает русский и английский языки; при первом запуске
используется русский.

Текущая версия умеет:

- одновременно показывать один или несколько файлов в двух панелях;
- лениво обходить группы, datasets, hard/soft/external и broken links;
- обнаруживать циклы hard links;
- показывать атрибуты, свойства хранения и ограниченные двумерные срезы N-D datasets;
- редактировать поддерживаемые scalar values и атрибуты в безопасной рабочей копии;
- создавать группы и переименовывать links;
- выполнять undo/redo, Save, Save As и Discard;
- проверять рабочую копию и создавать backup перед атомарной заменой оригинала.

Подробная матрица фактически реализованных возможностей находится в
[docs/hdf5-support-matrix.md](docs/hdf5-support-matrix.md).

## Установка для разработки

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
h5viewer
```

В Windows окружение активируется командой `.venv\Scripts\activate`.

## Проверки

```bash
ruff check .
ruff format --check .
mypy src/h5viewer
pytest
```

Состояние и следующие этапы разработки фиксируются в [PLANS.md](PLANS.md). Архитектура описана в
[docs/architecture.md](docs/architecture.md), а протокол безопасного сохранения — в
[docs/safe-saving.md](docs/safe-saving.md).
