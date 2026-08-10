# H5 Viewer

H5 Viewer — кроссплатформенное двухпанельное desktop-приложение для просмотра и безопасного
редактирования файлов HDF5. Интерфейс поддерживает русский и английский языки; при первом запуске
используется русский.

Текущая версия умеет:

- одновременно показывать один или несколько файлов в двух панелях;
- лениво обходить группы, datasets, hard/soft/external и broken links;
- обнаруживать циклы hard links;
- показывать атрибуты, свойства хранения и ограниченные двумерные срезы N-D datasets;
- разрешать object/region references, показывать region selection и переходить к доступной цели;
- показывать шкалы измерений и структурированные соответствия VDS без чтения payload;
- искать пути, типы, dataset metadata и ограниченные значения атрибутов;
- сравнивать документы панелей по структуре, атрибутам и данным блоками с настраиваемым допуском;
- атомарно экспортировать полный dataset в NPY или текущую полную 2-D projection в CSV;
- показывать line plot и heatmap текущей страницы через опциональный `pyqtgraph`;
- редактировать поддерживаемые scalar values и атрибуты в безопасной рабочей копии;
- создавать группы и datasets с настройкой dtype, shape, chunks, compression и fill value;
- безопасно расширять chunked datasets в пределах maxshape;
- создавать hard/soft/external links, безопасно удалять и переименовывать их;
- копировать (`F5`) и перемещать (`F6`) объекты между панелями;
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

Для визуализации числовых datasets установите опциональное дополнение:

```bash
python -m pip install -e '.[plots]'
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
