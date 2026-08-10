# Матрица поддержки HDF5

Обозначения: ✅ реализовано и тестируется; ◐ частично; — не реализовано.

| Возможность | Просмотр | Редактирование | Примечание |
|---|---:|---:|---|
| Groups и root group | ✅ | ✅ | Создание, move/rename и удаление с disk-backed undo |
| Numeric datasets | ✅ | ✅ | Создание, отдельные значения и безопасное расширение |
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

Уменьшение dataset через UI намеренно отключено: HDF5 сразу удаляет отброшенную область, поэтому
для корректного undo потребуется дисковый snapshot. Внутреннее уменьшение применяется только при
undo ранее выполненного расширения, когда стек команд гарантирует отсутствие пользовательских
изменений в удаляемой области.
