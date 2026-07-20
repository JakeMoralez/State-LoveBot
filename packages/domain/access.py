"""Access level constants (shared by bot and web).

Must stay compatible with `user_server_access.access_level` and Admin mirror.
"""

from __future__ import annotations

from enum import IntEnum


class AccessLevel(IntEnum):
    """Числовые уровни доступа (1–10)."""

    PGS = 1
    SUPERVISOR = 2
    ZGS = 3
    GS = 4
    ZGS_GOS = 5
    GS_GOS = 6
    CURATOR = 7
    ZGA = 8
    GA = 9
    DEVELOPER = 10


ACCESS_LEVEL_NAMES: dict[int, str] = {
    1: "ПГС",
    2: "Следящий",
    3: "ЗГС",
    4: "ГС",
    5: "ЗГС ГОС",
    6: "ГС ГОС",
    7: "Куратор",
    8: "ЗГА",
    9: "ГА",
    10: "Разработчик",
}
