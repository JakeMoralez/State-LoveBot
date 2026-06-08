"""Клавиатура подтверждения /msg."""

from __future__ import annotations

from vkbottle import Callback, Keyboard, KeyboardButtonColor


def create_msg_confirm_keyboard(token: str) -> str:
    kb = Keyboard(inline=True)
    kb.add(
        Callback("✅ Отправить", payload={"cmd": "msg_confirm", "token": token}),
        color=KeyboardButtonColor.POSITIVE,
    )
    kb.add(
        Callback("❌ Отмена", payload={"cmd": "msg_cancel", "token": token}),
        color=KeyboardButtonColor.NEGATIVE,
    )
    return kb.get_json()
