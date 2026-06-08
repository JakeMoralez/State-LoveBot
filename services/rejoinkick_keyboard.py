"""Клавиатура /rejoinkick ask — только «Кикнуть»."""

from __future__ import annotations

from vkbottle import Callback, Keyboard, KeyboardButtonColor


def create_rejoinkick_keyboard(peer_id: int, target_id: int) -> str:
    kb = Keyboard(inline=True)
    kb.add(
        Callback(
            "Кикнуть",
            payload={
                "cmd": "rejoinkick_kick",
                "peer_id": peer_id,
                "target_id": target_id,
            },
        ),
        color=KeyboardButtonColor.NEGATIVE,
    )
    return kb.get_json()
