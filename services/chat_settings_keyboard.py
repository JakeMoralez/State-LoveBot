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


def create_kind_keyboard(owner_id: int) -> str:
    from database.models.chat_kind import KIND_LABELS, ChatKind

    kb = Keyboard(inline=True)
    items = (
        (ChatKind.GENERAL, KIND_LABELS[ChatKind.GENERAL]),
        (ChatKind.LEADER, KIND_LABELS[ChatKind.LEADER]),
        (ChatKind.JUDGE, KIND_LABELS[ChatKind.JUDGE]),
        (ChatKind.STAFF, KIND_LABELS[ChatKind.STAFF]),
        (ChatKind.SLED_CA, KIND_LABELS[ChatKind.SLED_CA]),
        (ChatKind.STRUCTURE_LEAD, "Гл. след. админ."),
        (ChatKind.CONGRESS, KIND_LABELS[ChatKind.CONGRESS]),
    )
    first = True
    for kind, label in items:
        if not first:
            kb.row()
        first = False
        kb.add(
            Callback(
                label,
                payload={
                    "cmd": "chat_cfg",
                    "action": "kind",
                    "k": kind,
                    "owner": owner_id,
                },
            ),
            color=KeyboardButtonColor.PRIMARY
            if kind != ChatKind.GENERAL
            else KeyboardButtonColor.SECONDARY,
        )
    return kb.get_json()


def create_sphere_keyboard(kind: str, owner_id: int) -> str:
    from database.spheres import SPHERE_LABELS
    from services.chat_kind import spheres_for_kind

    kb = Keyboard(inline=True)
    first = True
    for key in spheres_for_kind(kind):
        if not first:
            kb.row()
        first = False
        kb.add(
            Callback(
                SPHERE_LABELS.get(key, key),
                payload={
                    "cmd": "chat_cfg",
                    "action": "ksphere",
                    "k": kind,
                    "s": key,
                    "owner": owner_id,
                },
            ),
            color=KeyboardButtonColor.PRIMARY,
        )
    return kb.get_json()
