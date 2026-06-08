"""Клавиатура действий с темой форума."""

from __future__ import annotations

import time

from vkbottle import Callback, Keyboard, KeyboardButtonColor


def create_thread_action_keyboard(thread_id: int, user_id: int) -> str:
    created_at = int(time.time())
    base = {
        "thread_id": thread_id,
        "creator_id": user_id,
        "created_at": created_at,
    }

    kb = Keyboard(inline=True)
    kb.add(
        Callback("🔒 Закрыть", payload={"cmd": "close", **base}),
        color=KeyboardButtonColor.PRIMARY,
    )
    kb.add(
        Callback("🔓 Открыть", payload={"cmd": "open", **base}),
        color=KeyboardButtonColor.PRIMARY,
    )
    kb.row()
    kb.add(
        Callback("📌 Закрепить", payload={"cmd": "pin", **base}),
        color=KeyboardButtonColor.PRIMARY,
    )
    kb.add(
        Callback("📌 Открепить", payload={"cmd": "unpin", **base}),
        color=KeyboardButtonColor.PRIMARY,
    )
    return kb.get_json()
