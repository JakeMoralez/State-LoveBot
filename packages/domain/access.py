"""Access level IntEnum stub (wave-0).

Канон имён/чисел: database/access_levels.py (= panel domain/access_levels.py).
Не дублировать правки здесь — правь канон и проверь parity-скрипт панели.
"""

from __future__ import annotations

from enum import IntEnum


class AccessLevel(IntEnum):
    PGS = 1
    SUPERVISOR = 2
    ZGS = 3
    GS = 4
    STRUCTURE_SUPERVISOR = 5
    ZGS_GOS = 6
    GS_GOS = 7
    CURATOR = 8
    ZGA = 9
    GA = 10
    DEVELOPER = 11


# Должно совпадать с database.access_levels.SHORT_NAMES
ACCESS_LEVEL_NAMES: dict[int, str] = {
    1: "ПГС",
    2: "Следящий",
    3: "ЗГС",
    4: "ГС",
    5: "Следящий структуры",
    6: "ЗГС ГОС",
    7: "ГС ГОС",
    8: "Куратор",
    9: "ЗГА",
    10: "ГА",
    11: "Разработчик",
}
