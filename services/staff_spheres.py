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

_POOL_TO_SPHERE: dict[str, str] = {
    "cab_min": CENTRAL_APPARATUS,
    "congress": CENTRAL_APPARATUS,
    "court": CENTRAL_APPARATUS,
    "info_court": CENTRAL_APPARATUS,
    "lead_co": CENTRAL_APPARATUS,
    "sled_co": CENTRAL_APPARATUS,
    "lead_md": DEFENSE,
    "sled_md": DEFENSE,
    "lead_gos": GOV_STRUCTURES,
    "sled_gos": GOV_STRUCTURES,
    "ruk_gos": GOV_STRUCTURES,
    "lead_mj": JUSTICE,
    "sled_mj": JUSTICE,
    "lead_mh": HEALTH,
    "sled_mh": HEALTH,
}


def allowed_sphere_keys_for_level(level: int) -> tuple[str, ...]:
    """1–4: министерства; 5–7: структуры; 8+: сервер. Как в панели."""
    if level >= AccessLevel.CURATOR:
        return (SERVER,)
    if level >= AccessLevel.STRUCTURE_SUPERVISOR:
        return (GOV_STRUCTURES, ILLEGAL_STRUCTURES)
    return (CENTRAL_APPARATUS, JUSTICE, DEFENSE, HEALTH)


def effective_grantable_sphere_keys(actor_level: int, actor_spheres: list[str]) -> set[str]:
    grantable = set(actor_spheres or [])
    if actor_level >= AccessLevel.CURATOR:
        grantable |= set(allowed_sphere_keys_for_level(AccessLevel.CURATOR))
    elif actor_level >= AccessLevel.STRUCTURE_SUPERVISOR:
        grantable |= {GOV_STRUCTURES, ILLEGAL_STRUCTURES}
    elif actor_level >= AccessLevel.ZGS:
        # ЗГС/ГС могут править свои сферы + tier министерств, которые у них есть
        grantable |= set(actor_spheres or [])
    return grantable


def pool_alias_to_sphere(alias: str | None, pool_name: str | None = None) -> str | None:
    text = " ".join(part for part in (alias or "", pool_name or "") if part).lower()
    if not text:
        return None
    for alias_key, sphere in _POOL_TO_SPHERE.items():
        if alias_key in text:
            return sphere
    compact = re.sub(r"[\s_\-]+", "", text)
    if any(token in text or token in compact for token in ("ца", "ca", "central", "аппарат", "cab")):
        return CENTRAL_APPARATUS
    if any(token in text or token in compact for token in ("мю", "mj", "justice", "юстиц")):
        return JUSTICE
    if any(token in text or token in compact for token in ("мо", "md", "defense", "обор", "минобор")):
        return DEFENSE
    if any(token in text or token in compact for token in ("мз", "mh", "health", "здрав")):
        return HEALTH
    if any(token in text or token in compact for token in ("гос", "gos", "gov", "государ")):
        return GOV_STRUCTURES
    if any(token in text or token in compact for token in ("нелег", "illegal", "нелегал")):
        return ILLEGAL_STRUCTURES
    return None


def parse_sphere_tokens(raw: str) -> list[str]:
    """Поддерживает 'ца, мю', 'ца мз', 'ца+мю', 'гос нелег' → ключи сфер."""
    text = (raw or "").strip()
    if not text:
        raise ValueError("Укажите сферы: ца, мю, мо, мз, гос, нелег, сервер")

    tokens = re.split(r"[,+\s]+", text.replace(";", ","))
    parts = [p.strip().lower() for p in tokens if p and p.strip()]
    result: list[str] = []
    seen: set[str] = set()
    friendly = "ца, мю, мо, мз, гос, нелег, сервер"
    for part in parts:
        key = _SPHERE_ALIASES.get(part)
        if not key:
            if part in ALL_SPHERE_KEYS:
                key = part
            else:
                raise ValueError(f"Неизвестная сфера «{part}». Доступны: {friendly}")
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


def constrain_spheres_for_actor(
    actor_level: int,
    actor_spheres: list[str],
    target_current: list[str],
    requested: list[str],
    access_level: int,
) -> list[str]:
    """ЗГС/ГС меняет только свои сферы; выше — по tier."""
    grantable = effective_grantable_sphere_keys(actor_level, actor_spheres)
    current = set(target_current or [])
    requested_set = set(requested or [])

    locked = current - grantable
    if not locked.issubset(requested_set):
        missing = locked - requested_set
        raise ValueError(
            f"Нельзя снять сферу без прав: {format_spheres_display(sorted(missing))}"
        )

    added = requested_set - current
    illegal_add = added - grantable
    if illegal_add:
        raise ValueError(
            f"Можно выдавать только свои сферы: {format_spheres_display(sorted(illegal_add))}"
        )

    removed = current - requested_set
    illegal_remove = removed - grantable
    if illegal_remove:
        raise ValueError(
            f"Нельзя снять сферу без прав: {format_spheres_display(sorted(illegal_remove))}"
        )

    return validate_spheres(list(requested_set), access_level)


__all__ = [
    "allowed_sphere_keys_for_level",
    "constrain_spheres_for_actor",
    "effective_grantable_sphere_keys",
    "format_spheres_display",
    "parse_sphere_tokens",
    "pool_alias_to_sphere",
    "validate_spheres",
]
