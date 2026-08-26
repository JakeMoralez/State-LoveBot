"""Inline-клавиатуры /chatsettings."""

from __future__ import annotations

from vkbottle import Callback, Keyboard, KeyboardButtonColor

from services.chat_settings_ui import CHAT_SETTINGS


def create_open_edit_keyboard(owner_id: int) -> str:
    kb = Keyboard(inline=True)
    kb.add(
        Callback(
            "⚙ Изменить настройки",
            payload={"cmd": "chat_cfg", "action": "edit", "owner": owner_id},
        ),
        color=KeyboardButtonColor.PRIMARY,
    )
    return kb.get_json()


def create_value_keyboard(setting_key: str, owner_id: int) -> str:
    setting = CHAT_SETTINGS[setting_key]
    kb = Keyboard(inline=True)
    first = True
    for mode, label in setting.value_buttons:
        if not first:
            kb.row()
        first = False
        color = KeyboardButtonColor.POSITIVE if mode != "off" else KeyboardButtonColor.SECONDARY
        if mode == "ask":
            color = KeyboardButtonColor.SECONDARY
        kb.add(
            Callback(
                label,
                payload={
                    "cmd": "chat_cfg",
                    "action": "set",
                    "key": setting_key,
                    "value": mode,
                    "owner": owner_id,
                },
            ),
            color=color,
        )
    return kb.get_json()
