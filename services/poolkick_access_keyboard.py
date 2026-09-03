"""Клавиатура выбора действий с доступами после /poolkick."""

from __future__ import annotations

from vkbottle import Callback, Keyboard, KeyboardButtonColor


def create_poolkick_access_keyboard(
    token: str,
    *,
    has_staff: bool,
    has_roles: bool,
) -> str:
    kb = Keyboard(inline=True)
    kb.add(
        Callback(
            "Снять всё",
            payload={"cmd": "pk_access", "token": token, "choice": "all"},
        ),
        color=KeyboardButtonColor.NEGATIVE,
    )
    if has_roles:
        kb.row()
        kb.add(
            Callback(
                "Только роли",
                payload={"cmd": "pk_access", "token": token, "choice": "roles"},
            ),
            color=KeyboardButtonColor.SECONDARY,
        )
    if has_staff:
        kb.row()
        kb.add(
            Callback(
                "Только сферы",
                payload={"cmd": "pk_access", "token": token, "choice": "spheres"},
            ),
            color=KeyboardButtonColor.SECONDARY,
        )
    kb.row()
    kb.add(
        Callback(
            "Не трогать",
            payload={"cmd": "pk_access", "token": token, "choice": "skip"},
        ),
        color=KeyboardButtonColor.PRIMARY,
    )
    return kb.get_json()
