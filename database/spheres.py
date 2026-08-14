"""Сферы следящих — ключи совпадают с панелью State-LoveAdmin."""

from __future__ import annotations

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

ALL_SPHERE_KEYS: tuple[str, ...] = (
    CENTRAL_APPARATUS,
    JUSTICE,
    DEFENSE,
    HEALTH,
    GOV_STRUCTURES,
    ILLEGAL_STRUCTURES,
    SERVER,
)


def format_spheres_display(spheres: list[str]) -> str:
    if not spheres:
        return "—"
    return ", ".join(SPHERE_LABELS.get(k, k) for k in spheres)
