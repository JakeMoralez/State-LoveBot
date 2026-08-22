"""Разбор и валидация сфер следящих — parity с панелью."""

from __future__ import annotations

import re

from database.models.user import AccessLevel
from database.spheres import (
    ALL_SPHERE_KEYS,
    CENTRAL_APPARATUS,
    DEFENSE,
    GOV_STRUCTURES,
    HEALTH,
    ILLEGAL_STRUCTURES,
    JUSTICE,
    SERVER,
    format_spheres_display,
)

_SPHERE_ALIASES: dict[str, str] = {
    "ca": CENTRAL_APPARATUS,
    "ца": CENTRAL_APPARATUS,
    "центральныйаппарат": CENTRAL_APPARATUS,
    "central_apparatus": CENTRAL_APPARATUS,
    "мю": JUSTICE,
    "юстиц": JUSTICE,
    "justice": JUSTICE,
    "мо": DEFENSE,
    "оборон": DEFENSE,
    "defense": DEFENSE,
    "мз": HEALTH,
    "здрав": HEALTH,
    "health": HEALTH,
    "гос": GOV_STRUCTURES,
    "gos": GOV_STRUCTURES,
    "gov": GOV_STRUCTURES,
    "gov_structures": GOV_STRUCTURES,
    "нелег": ILLEGAL_STRUCTURES,
    "illegal": ILLEGAL_STRUCTURES,
    "illegal_structures": ILLEGAL_STRUCTURES,
    "server": SERVER,
    "сервер": SERVER,
}


def allowed_sphere_keys_for_level(level: int) -> tuple[str, ...]:
    if level >= AccessLevel.CURATOR:
        return (SERVER,)
    if level >= AccessLevel.STRUCTURE_SUPERVISOR:
        return (GOV_STRUCTURES, ILLEGAL_STRUCTURES)
    return (CENTRAL_APPARATUS, JUSTICE, DEFENSE, HEALTH)


def parse_sphere_tokens(raw: str) -> list[str]:
    """Поддерживает 'ца, мю', 'ца мз', 'ца+мю', 'гос нелег' → ключи сфер."""
    text = (raw or "").strip()
    if not text:
        raise ValueError("Укажите сферы через запятую или пробел (ца, мю, гос, …)")

    tokens = re.split(r"[,+\s]+", text.replace(";", ","))
    parts = [p.strip().lower() for p in tokens if p and p.strip()]
    result: list[str] = []
    seen: set[str] = set()
    for part in parts:
        key = _SPHERE_ALIASES.get(part)
        if not key:
            if part in ALL_SPHERE_KEYS:
                key = part
            else:
                allowed = ", ".join(sorted(set(_SPHERE_ALIASES.keys())))
                raise ValueError(f"Неизвестная сфера «{part}». Доступны: {allowed}")
        if key not in seen:
            seen.add(key)
            result.append(key)
    if not result:
        raise ValueError("Укажите хотя бы одну сферу")
    return result


def validate_spheres(spheres: list[str], access_level: int | None = None) -> list[str]:
    if not spheres:
        raise ValueError("Выберите хотя бы одну сферу")
    seen: set[str] = set()
    result: list[str] = []
    for key in spheres:
        k = (key or "").strip()
        if not k or k in seen:
            continue
        if k not in ALL_SPHERE_KEYS:
            raise ValueError(f"Неизвестная сфера: {k}")
        seen.add(k)
        result.append(k)
    if not result:
        raise ValueError("Выберите хотя бы одну сферу")
    if access_level is not None:
        allowed = set(allowed_sphere_keys_for_level(access_level))
        bad = [k for k in result if k not in allowed]
        if bad:
            if access_level >= AccessLevel.CURATOR:
                tier = "сервер"
            elif access_level >= AccessLevel.STRUCTURE_SUPERVISOR:
                tier = "государственные или нелегальные структуры"
            else:
                tier = "сферы министерств (ЦА, МЮ, МО, МЗ)"
            raise ValueError(f"Для этого уровня доступны только {tier}")
    return result


__all__ = [
    "format_spheres_display",
    "parse_sphere_tokens",
    "validate_spheres",
]
