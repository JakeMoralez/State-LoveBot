"""Единый источник правил сфер (Single Source of Truth).

Канон: этот файл в State-LoveAdmin.
Зеркало 1:1: State-LoveBot/database/sphere_grant_rules.py
(править только здесь, затем скопировать в бот).

Frontend не дублирует grant-логику: берёт grantable_spheres из /api/auth/me
и permissions карточки. Здесь же — tier «какие сферы может ИМЕТЬ уровень».

Пороги совпадают с AccessLevel: STRUCTURE_SUPERVISOR=5, CURATOR=8.
"""

from __future__ import annotations

# --- AccessLevel thresholds (без импорта моделей — файл копируется в бот) ---
STRUCTURE_SUPERVISOR_LEVEL = 5
CURATOR_LEVEL = 8

CENTRAL_APPARATUS = "central_apparatus"
JUSTICE = "justice"
DEFENSE = "defense"
HEALTH = "health"
GOV_STRUCTURES = "gov_structures"
ILLEGAL_STRUCTURES = "illegal_structures"
SERVER = "server"

SPHERE_LABELS: dict[str, str] = {
    CENTRAL_APPARATUS: "Центральный аппарат",
    JUSTICE: "Министерство Юстиции",
    DEFENSE: "Министерство Обороны",
    HEALTH: "Министерство Здравоохранения",
    GOV_STRUCTURES: "Государственные структуры",
    ILLEGAL_STRUCTURES: "Нелегальные структуры",
    SERVER: "Сервер",
}

MINISTRY_SPHERE_KEYS: tuple[str, ...] = (
    CENTRAL_APPARATUS,
    JUSTICE,
    DEFENSE,
    HEALTH,
)

STRUCTURE_SPHERE_KEYS: tuple[str, ...] = (
    GOV_STRUCTURES,
    ILLEGAL_STRUCTURES,
)

ALL_SPHERE_KEYS: tuple[str, ...] = MINISTRY_SPHERE_KEYS + STRUCTURE_SPHERE_KEYS + (SERVER,)


def format_spheres_display(spheres: list[str]) -> str:
    if not spheres:
        return "—"
    return ", ".join(SPHERE_LABELS.get(k, k) for k in spheres)


def allowed_sphere_keys_for_level(level: int) -> tuple[str, ...]:
    """Какие сферы может иметь пользователь данного уровня (не путать с выдачей).

    1–4: министерства; 5–7: структуры; 8+: сервер.
    """
    if level >= CURATOR_LEVEL:
        return (SERVER,)
    if level >= STRUCTURE_SUPERVISOR_LEVEL:
        return STRUCTURE_SPHERE_KEYS
    return MINISTRY_SPHERE_KEYS


def effective_grantable_sphere_keys(
    actor_level: int,
    actor_spheres: list[str] | None,
) -> set[str]:
    """Сферы, которые актор может выдавать и снимать у других.

    - Куратор (8+): все сферы
    - Следящий структуры / ЗГС·ГС ГОС (5–7): министерства + структуры
    - Ниже: только свои текущие сферы (actor_spheres)
    """
    grantable = set(actor_spheres or [])
    if actor_level >= CURATOR_LEVEL:
        grantable |= set(ALL_SPHERE_KEYS)
    elif actor_level >= STRUCTURE_SUPERVISOR_LEVEL:
        grantable |= set(MINISTRY_SPHERE_KEYS) | set(STRUCTURE_SPHERE_KEYS)
    return grantable
