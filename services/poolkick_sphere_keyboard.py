"""Клавиатура выбора сферы после /poolkick."""

from __future__ import annotations

from vkbottle import Callback, Keyboard, KeyboardButtonColor

from database.spheres import SPHERE_LABELS


def create_poolkick_sphere_keyboard(
    token: str,
    target_spheres: list[str],
    *,
    owner_id: int,
) -> str:
    kb = Keyboard(inline=True)
    first = True
    for key in target_spheres:
        label = SPHERE_LABELS.get(key, key)
        short = label.split()[-1] if label else key
        if len(short) > 20:
            short = short[:17] + "…"
        if not first:
            kb.row()
        first = False
        kb.add(
            Callback(
                f"Снять {short}",
                payload={
                    "cmd": "pk_sphere",
                    "token": token,
                    "choice": key,
                    "owner": owner_id,
                },
            ),
            color=KeyboardButtonColor.SECONDARY,
        )
    if not first:
        kb.row()
    kb.add(
        Callback(
            "Снять полностью",
            payload={
                "cmd": "pk_sphere",
                "token": token,
                "choice": "full",
                "owner": owner_id,
            },
        ),
        color=KeyboardButtonColor.NEGATIVE,
    )
    kb.add(
        Callback(
            "Не снимать",
            payload={
                "cmd": "pk_sphere",
                "token": token,
                "choice": "skip",
                "owner": owner_id,
            },
        ),
        color=KeyboardButtonColor.PRIMARY,
    )
    return kb.get_json()
