# Матрица поддержки HDF5

Обозначения: ✅ реализовано и тестируется; ◐ частично; — не реализовано.

| Возможность | Просмотр | Редактирование | Примечание |
|---|---:|---:|---|
| Groups и root group | ✅ | ◐ | Создание и rename; удаление группы пока отсутствует в UI |
| Numeric datasets | ✅ | ✅ | Создание, отдельные значения и безопасное расширение |
| Scalar datasets | ✅ | ✅ | Для поддерживаемых dtype |
| Null/empty datasets | ✅ | — | Корректно показываются без чтения payload |
| N-D datasets | ✅ | ✅ | Двумерная проекция с фиксированными индексами |
| Fixed/vlen strings | ✅ | ✅ | Fixed strings защищены от молчаливого обрезания |
| Compound dtype | ✅ | — | Безопасный read-only fallback |
| Enum dtype | ✅ | ✅ | Допускается имя enum либо числовое значение |
| Array/vlen sequence dtype | ◐ | — | Metadata и доступное значение |
| Object/region references | ✅ | — | Metadata и представление значения; переход к цели ещё не реализован |
| Attributes | ✅ | ✅ | Scalar и JSON-совместимые массивы с неизменным shape/dtype |
| Hard links и aliases | ✅ | ◐ | Identity и циклы; создание hard link пока отсутствует |
| Soft links | ✅ | — | Показывается target и broken state |
| External links | ✅ | — | Показывается файл, target и broken state |
| Committed datatype | ✅ | — | Metadata |
| Chunking/layout/fill value | ✅ | ✅ | Настройка при создании dataset |
| Filter pipeline | ✅ | ◐ | Создание с gzip/lzf, shuffle и Fletcher32 |
| VDS mappings | ✅ | — | Metadata mappings |
| Dimension scales | ✅ | — | Флаги и labels |
| External raw storage | ✅ | — | Metadata |
| Copy между файлами | ✅ | ✅ | Без раскрытия soft/external/reference targets; undoable |
| Move между файлами | — | — | Требует координации двух независимых commit |
| Metadata search/compare | — | — | Следующий этап |

Уменьшение dataset через UI намеренно отключено: HDF5 сразу удаляет отброшенную область, поэтому
для корректного undo потребуется дисковый snapshot. Внутреннее уменьшение применяется только при
undo ранее выполненного расширения, когда стек команд гарантирует отсутствие пользовательских
изменений в удаляемой области.
