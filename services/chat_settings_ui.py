"""Тексты и описание настроек беседы (/chatsettings)."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from vkbottle import API

from database.models.chat_settings import ChatPeerSettings, GuardMode
from database.repository.chat_repo import ChatRepository
from database.repository.chat_settings_repo import ChatSettingsRepository

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ChatSettingDef:
    number: int
    key: str
    slug: str
    title: str
    field: str
    value_buttons: tuple[tuple[str, str], ...]
    allow_ask: bool = False

    def format_line(self, settings: ChatPeerSettings) -> str:
        mode = getattr(settings, self.field, GuardMode.OFF) or GuardMode.OFF
        if self.field == "kick_on_leave":
            mode = ChatSettingsRepository.effective_kick_on_leave(settings)
        elif self.field == "kick_on_rejoin":
            mode = ChatSettingsRepository.effective_kick_on_rejoin(settings)
        icon = "⛔" if mode == GuardMode.OFF else "✅"
        label = ChatSettingsRepository.setting_value_label(self.field, mode)
        return f"{icon} [№{self.number} / {self.slug}] — {self.title} — {label}"


CHAT_SETTINGS: dict[str, ChatSettingDef] = {
    "kick_on_leave": ChatSettingDef(
        number=1,
        key="kick_on_leave",
        slug="kickOnLeave",
        title="Быстрый кик",
        field="kick_on_leave",
        allow_ask=True,
        value_buttons=(
            (GuardMode.ON, "Кикать"),
            (GuardMode.OFF, "Ничего"),
            (GuardMode.ASK, "Спросить"),
        ),
    ),
    "kick_on_rejoin": ChatSettingDef(
        number=2,
        key="kick_on_rejoin",
        slug="kickOnRejoin",
        title="Кик при возвращении",
        field="kick_on_rejoin",
        value_buttons=(
            (GuardMode.ON, "Кикать"),
            (GuardMode.OFF, "Ничего"),
        ),
    ),
    "auto_mute_on_join": ChatSettingDef(
        number=3,
        key="auto_mute_on_join",
        slug="autoMuteOnJoin",
        title="Автомут при добавлении",
        field="auto_mute_on_join",
        value_buttons=(
            (GuardMode.ON, "Вкл"),
            (GuardMode.OFF, "Выкл"),
        ),
    ),
}

CHAT_SETTINGS_BY_NUMBER = {
    setting.number: setting for setting in CHAT_SETTINGS.values()
}


async def resolve_chat_display(api: API, peer_id: int) -> str:
    chat = await ChatRepository.get_by_peer_id(peer_id)
    title: str | None = None
    if chat and chat.title:
        title = chat.title.strip()
    if not title:
        try:
            conv = await api.messages.get_conversations_by_id(peer_ids=[peer_id])
            if conv.items:
                title = (conv.items[0].chat_settings.title or "").strip()
        except Exception as exc:
            logger.debug("chat title fetch failed peer=%s: %s", peer_id, exc)
    if not title:
        title = f"Беседа {peer_id}"

    suffix = ""
    if chat and chat.alias:
        suffix = f" ({chat.alias})"
    return f"«{title}»{suffix}"


async def apply_setting(
    peer_id: int,
    field: str,
    mode: str,
    *,
    updated_by: int | None,
) -> ChatPeerSettings:
    allow_ask = field == "kick_on_leave"
    normalized = ChatSettingsRepository.normalize_mode(mode, allow_ask=allow_ask)
    if not normalized:
        raise ValueError("Недопустимое значение")
    if field == "kick_on_rejoin" and normalized == GuardMode.ASK:
        raise ValueError("Для возвращения доступны только кик или ничего")

    settings = await ChatSettingsRepository.set_mode(
        peer_id,
        field,
        normalized,
        updated_by=updated_by,
        allow_ask=allow_ask,
    )
    return settings


async def format_settings_overview(api: API, peer_id: int) -> str:
    settings = await ChatSettingsRepository.get(peer_id)
    chat_label = await resolve_chat_display(api, peer_id)
    leave = ChatSettingsRepository.effective_kick_on_leave(settings)
    rejoin = ChatSettingsRepository.effective_kick_on_rejoin(settings)
    mute = settings.auto_mute_on_join or GuardMode.OFF

    lines = [
        "⚙️ Настройки беседы",
        "",
        f"⭐ Конференция: {chat_label}",
        "",
        "🔁 Кик при выходе — "
        f"{ChatSettingsRepository.leave_mode_label(leave)}",
        "↩️ Кик при возвращении — "
        f"{ChatSettingsRepository.rejoin_mode_label(rejoin)}",
        "🔇 Автомут при добавлении — "
        f"{ChatSettingsRepository.toggle_label(mute)}",
        "",
        "Кик при выходе: кикать — исключить сразу; спрашивать — кнопка «Кикнуть»; "
        "ничего — только уведомление.",
        "Кик при возвращении: если участник сам выходил — кикнуть или пропустить.",
        "Автомут: бессрочный мут новым участникам при входе в беседу.",
    ]
    return "\n".join(lines)


async def format_settings_edit_panel(api: API, peer_id: int) -> str:
    settings = await ChatSettingsRepository.get(peer_id)
    chat_label = await resolve_chat_display(api, peer_id)
    lines = [
        f"⭐ Конференция: {chat_label}",
        "",
        "☢ Доступные к изменению пункты ☢",
    ]
    for number in sorted(CHAT_SETTINGS_BY_NUMBER):
        lines.append(CHAT_SETTINGS_BY_NUMBER[number].format_line(settings))
    lines.extend(
        [
            "",
            "👇 Напишите следующим сообщением пункт, который хотите отредактировать 👇",
        ]
    )
    return "\n".join(lines)


def format_setting_updated(field: str, mode: str) -> str:
    title = CHAT_SETTINGS.get(field)
    name = title.title if title else field
    label = ChatSettingsRepository.setting_value_label(field, mode)
    if mode == GuardMode.OFF and field == "auto_mute_on_join":
        tail = " ⛔"
    elif mode == GuardMode.OFF:
        tail = " ⛔"
    else:
        tail = " ✅"
    return f"✅ Вы обновили «{name}» → {label}{tail}"
