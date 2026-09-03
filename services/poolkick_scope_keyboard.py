"""Клавиатура выбора scope для /poolkick."""

from __future__ import annotations

from vkbottle import Callback, Keyboard, KeyboardButtonColor

from database.spheres import GOV_STRUCTURES
from services.staff_nickname import MINISTRY_NICK_TAGS, STRUCTURE_NICK_TAGS


def _short_sphere(sphere: str) -> str:
    return (
        MINISTRY_NICK_TAGS.get(sphere)
        or STRUCTURE_NICK_TAGS.get(sphere)
        or sphere
    )


def create_poolkick_scope_keyboard(
    token: str,
    *,
    main_spheres: list[str],
    has_this: bool,
    has_gos_only: bool = False,
    prefer_sphere: str | None = None,
) -> str:
    spheres = list(main_spheres)
    if prefer_sphere and prefer_sphere in spheres:
        spheres.remove(prefer_sphere)
        spheres.insert(0, prefer_sphere)

    # Лимит inline-кнопок VK — держим разумный набор
    if len(spheres) > 4:
        spheres = spheres[:4]

    kb = Keyboard(inline=True)
    kb.add(
        Callback(
            "Из всех бесед",
            payload={"cmd": "pk_scope", "token": token, "scope": "all"},
        ),
        color=KeyboardButtonColor.NEGATIVE,
    )

    for sphere in spheres:
        short = _short_sphere(sphere)
        kb.row()
        kb.add(
            Callback(
                f"{short} + гос",
                payload={
                    "cmd": "pk_scope",
                    "token": token,
                    "scope": "sphere_gos",
                    "sphere": sphere,
                },
            ),
            color=KeyboardButtonColor.PRIMARY,
        )
        kb.add(
            Callback(
                f"Только {short}",
                payload={
                    "cmd": "pk_scope",
                    "token": token,
                    "scope": "sphere",
                    "sphere": sphere,
                },
            ),
            color=KeyboardButtonColor.SECONDARY,
        )

    if has_gos_only and GOV_STRUCTURES not in main_spheres and not spheres:
        kb.row()
        kb.add(
            Callback(
                "Только гос",
                payload={"cmd": "pk_scope", "token": token, "scope": "gos_only"},
            ),
            color=KeyboardButtonColor.SECONDARY,
        )

    if has_this:
        kb.row()
        kb.add(
            Callback(
                "Только из этой",
                payload={"cmd": "pk_scope", "token": token, "scope": "this"},
            ),
            color=KeyboardButtonColor.POSITIVE,
        )

    return kb.get_json()
