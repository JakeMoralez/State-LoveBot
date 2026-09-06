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


# VK inline: не больше 6 кнопок, иначе messages.send падает.
_INLINE_MAX = 6


def create_kind_keyboard(owner_id: int, *, page: int = 1) -> str:
    from services.chat_settings_ui import KIND_PICK_ITEMS

    kb = Keyboard(inline=True)
    if page <= 1:
        shown = KIND_PICK_ITEMS[:5]
        extra = ("kpage", "Ещё")
    else:
        shown = KIND_PICK_ITEMS[5:]
        extra = ("kpage1", "Назад")
    first = True
    for kind, label in shown:
        if not first:
            kb.row()
        first = False
        kb.add(
            Callback(
                label[:40],
                payload={
                    "cmd": "chat_cfg",
                    "action": "kind",
                    "k": kind,
                    "owner": owner_id,
                },
            ),
            color=KeyboardButtonColor.PRIMARY if kind != "general" else KeyboardButtonColor.SECONDARY,
        )
    kb.row()
    kb.add(
        Callback(
            extra[1],
            payload={
                "cmd": "chat_cfg",
                "action": extra[0],
                "owner": owner_id,
            },
        ),
        color=KeyboardButtonColor.SECONDARY,
    )
    return kb.get_json()


def create_sphere_keyboard(kind: str, owner_id: int, *, page: int = 0) -> str:
    from database.spheres import SPHERE_LABELS
    from services.chat_kind import spheres_for_kind

    keys = list(spheres_for_kind(kind))
    kb = Keyboard(inline=True)
    if len(keys) <= _INLINE_MAX:
        chunk = keys
        more = None
    else:
        size = _INLINE_MAX - 1
        start = page * size
        chunk = keys[start : start + size]
        more = "spage" if start + size < len(keys) else "spage0"
    first = True
    for key in chunk:
        if not first:
            kb.row()
        first = False
        kb.add(
            Callback(
                (SPHERE_LABELS.get(key, key))[:40],
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
    if more:
        kb.row()
        kb.add(
            Callback(
                "Ещё" if more == "spage" else "Назад",
                payload={
                    "cmd": "chat_cfg",
                    "action": more,
                    "k": kind,
                    "p": page + 1 if more == "spage" else 0,
                    "owner": owner_id,
                },
            ),
            color=KeyboardButtonColor.SECONDARY,
        )
    return kb.get_json()
