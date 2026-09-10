"""Сферы следящих — ключи и правила из единого канона sphere_grant_rules."""

from __future__ import annotations

from database.sphere_grant_rules import (  # noqa: F401 — re-export
    ALL_SPHERE_KEYS,
    CENTRAL_APPARATUS,
    CURATOR_LEVEL,
    DEFENSE,
    GOV_STRUCTURES,
    HEALTH,
    ILLEGAL_STRUCTURES,
    JUSTICE,
    MINISTRY_SPHERE_KEYS,
    SERVER,
    SPHERE_LABELS,
    STRUCTURE_SPHERE_KEYS,
    STRUCTURE_SUPERVISOR_LEVEL,
    allowed_sphere_keys_for_level,
    effective_grantable_sphere_keys,
    format_spheres_display,
)

__all__ = [
    "ALL_SPHERE_KEYS",
    "CENTRAL_APPARATUS",
    "CURATOR_LEVEL",
    "DEFENSE",
    "GOV_STRUCTURES",
    "HEALTH",
    "ILLEGAL_STRUCTURES",
    "JUSTICE",
    "MINISTRY_SPHERE_KEYS",
    "SERVER",
    "SPHERE_LABELS",
    "STRUCTURE_SPHERE_KEYS",
    "STRUCTURE_SUPERVISOR_LEVEL",
    "allowed_sphere_keys_for_level",
    "effective_grantable_sphere_keys",
    "format_spheres_display",
]
