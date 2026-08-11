# Матрица поддержки HDF5

Обозначения: ✅ реализовано и тестируется; ◐ частично; — не реализовано.

Матрица сверяется с программно созданными fixtures и интеграционными тестами; реальные
пользовательские файлы в destructive-проверках не используются.

| Возможность | Просмотр | Редактирование | Примечание |
|---|---:|---:|---|
| Groups и root group | ✅ | ✅ | Создание, move/rename и удаление с disk-backed undo |
| Numeric datasets | ✅ | ✅ | Создание, значения и resize; уменьшение с полным disk-backed undo |
| Scalar datasets | ✅ | ✅ | Для поддерживаемых dtype |
| Null/empty datasets | ✅ | — | Корректно показываются без чтения payload |
| N-D datasets | ✅ | ✅ | Двумерная проекция с фиксированными индексами |
| Fixed/vlen strings | ✅ | ✅ | Fixed strings защищены от молчаливого обрезания |
| Compound dtype | ✅ | — | Безопасный read-only fallback |
| Enum dtype | ✅ | ✅ | Допускается имя enum либо числовое значение |
| Array/vlen sequence dtype | ◐ | — | Metadata и доступное значение |
| Object/region references | ✅ | — | Ограниченный список, region selection и переход к доступной цели |
| Attributes | ✅ | ✅ | Scalar и JSON-совместимые массивы с неизменным shape/dtype |
| Hard links и aliases | ✅ | ✅ | Identity, циклы, создание и точное undo alias |
| Soft links | ✅ | ✅ | Создание, target, broken state и undo |
| External links | ✅ | ✅ | Создание, файл, target, broken state и undo |
| Committed datatype | ✅ | — | Metadata |
| Chunking/layout/fill value | ✅ | ✅ | Настройка при создании dataset |
| Filter pipeline | ✅ | ◐ | Создание с gzip/lzf, shuffle и Fletcher32 |
| VDS mappings | ✅ | — | Исходный файл/dataset и обе selection для каждого mapping |
| Dimension scales | ✅ | — | Labels и пути всех шкал по осям |
| External raw storage | ✅ | — | Metadata |
| Copy между файлами | ✅ | ✅ | Без раскрытия soft/external/reference targets; undoable |
| Move между файлами | ✅ | ✅ | Парный undo/redo; сохранение двух файлов неатомарно |
| Metadata search/compare | ✅ | — | Поиск с лимитом; сравнение структуры и данных блоками до 4 МиБ |
| Export CSV/NPY | ✅ | — | CSV для полной текущей projection; полный NPY порционным memory map |
| Numeric visualization | ✅ | — | Line/heatmap текущей страницы; optional `pyqtgraph` |

Перед уменьшением dataset создаётся полная копия рабочей версии HDF5. Это требует дополнительного
места примерно с размер рабочего файла, но точно сохраняет payload, типы, attributes, hard-link
aliases и references. При undo снимок атомарно возвращается на место рабочей копии; redo создаёт
новый снимок перед повторным уменьшением.
