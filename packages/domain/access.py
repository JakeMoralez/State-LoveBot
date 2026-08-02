"""Access level constants (shared by bot and web).

Must stay compatible with `user_server_access.access_level` and Admin mirror.
"""

from __future__ import annotations

from enum import IntEnum


class AccessLevel(IntEnum):
    """Числовые уровни доступа (1–11)."""

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
