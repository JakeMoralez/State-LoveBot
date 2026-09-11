"""Единый каталог уровней доступа 1–11 (Single Source of Truth).

Канон: этот файл в State-LoveAdmin.
Зеркало 1:1: State-LoveBot/database/access_levels.py
Frontend: frontend/src/lib/accessLevels.ts — короткие/полные имена должны совпадать.
Проверка: python backend/scripts/check_access_levels_parity.py

Править только здесь, затем скопировать зеркало в бот и сверить FE.
"""

from __future__ import annotations

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

# Краткие названия (колонка / бейджи / AccessLevel.NAMES)
SHORT_NAMES: dict[int, str] = {
    1: "ПС",
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

# Полные названия ролей (реестр «Доступ»)
ROLE_TITLES: dict[int, str] = {
    1: "Помощник следящих",
    2: "Следящий",
    3: "Зам. Главного следящего сферы",
    4: "Главный следящий сферы",
    5: "Следящий структуры",
    6: "Зам. Главного следящего структуры",
    7: "Главный следящий структуры",
    8: "Куратор",
    9: "Зам. Главного Администратора",
    10: "Главный Администратор",
    11: "Разработчик",
}

LEVELS: tuple[int, ...] = tuple(range(1, 12))


def short_name(level: int) -> str:
    return SHORT_NAMES.get(level, f"Уровень {level}")


def role_title(level: int) -> str:
    return ROLE_TITLES.get(level, short_name(level))
