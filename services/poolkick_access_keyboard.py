"""Клавиатура выбора действий с доступами после /poolkick."""

from __future__ import annotations

from vkbottle import Callback, Keyboard, KeyboardButtonColor


def create_poolkick_access_keyboard(
    token: str,
    *,
    owner_id: int,
    has_staff: bool,
    has_poolkick_roles: bool,
) -> str:
    kb = Keyboard(inline=True)
    first = True
    if has_staff or has_poolkick_roles:
        kb.add(
            Callback(
                "Снять всё",
                payload={
                    "cmd": "pk_access",
                    "token": token,
                    "choice": "all",
                    "owner": owner_id,
                },
            ),
            color=KeyboardButtonColor.NEGATIVE,
        )
        first = False
    if has_poolkick_roles:
        if not first:
            kb.row()
        kb.add(
            Callback(
                "Только роли",
                payload={
                    "cmd": "pk_access",
                    "token": token,
                    "choice": "roles",
                    "owner": owner_id,
                },
            ),
            color=KeyboardButtonColor.SECONDARY,
        )
        first = False
    if has_staff:
        if not first:
            kb.row()
        kb.add(
            Callback(
                "Только сферы",
                payload={
                    "cmd": "pk_access",
                    "token": token,
                    "choice": "spheres",
                    "owner": owner_id,
                },
            ),
            color=KeyboardButtonColor.SECONDARY,
        )
        first = False
    if not first:
        kb.row()
    kb.add(
        Callback(
            "Не трогать",
            payload={
                "cmd": "pk_access",
                "token": token,
                "choice": "skip",
                "owner": owner_id,
            },
        ),
        color=KeyboardButtonColor.PRIMARY,
    )
    return kb.get_json()
