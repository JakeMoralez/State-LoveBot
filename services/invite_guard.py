"""Настройка rejoinkick: on — автокик, ask — кнопка «Кикнуть»."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from vkbottle import API

from database.models.chat_settings import GuardMode
from database.repository.chat_settings_repo import ChatSettingsRepository
from services.display_name import DisplayNameService
from services.moderation import ModerationService
from services.rejoinkick_keyboard import create_rejoinkick_keyboard

logger = logging.getLogger(__name__)


@dataclass
class ChatNotice:
    text: str
    keyboard: str | None = None


async def _kick_on_leave(
    moderation: ModerationService,
    peer_id: int,
    user_id: int,
) -> bool:
    await ChatSettingsRepository.record_voluntary_leave(peer_id, user_id)
    result = await moderation.kick_from_chat(peer_id, user_id)
    if result.success:
        await ChatSettingsRepository.clear_left_record(peer_id, user_id)
        return True
    logger.info(
        "rejoinkick on: leave-kick deferred peer=%s user=%s (%s)",
        peer_id,
        user_id,
        result.error,
    )
    return False


async def build_rejoinkick_ask_leave(
    api: API,
    *,
    peer_id: int,
    target_id: int,
) -> ChatNotice:
    await ChatSettingsRepository.record_voluntary_leave(peer_id, target_id)
    link = await DisplayNameService(api).link_user(target_id)
    return ChatNotice(
        text=f"{link} покинул беседу.",
        keyboard=create_rejoinkick_keyboard(peer_id, target_id),
    )


async def build_rejoinkick_ask_rejoin(
    api: API,
    *,
    peer_id: int,
    target_id: int,
) -> ChatNotice:
    link = await DisplayNameService(api).link_user(target_id)
    return ChatNotice(
        text=f"{link} вернулся в беседу.",
        keyboard=create_rejoinkick_keyboard(peer_id, target_id),
    )


async def format_rejoinkick_action_message(
    api: API,
    *,
    actor_id: int,
    target_id: int,
) -> str:
    names = DisplayNameService(api)
    actor_m = await names.link_user(actor_id)
    target_m = await names.link_user(target_id)
    return f"{actor_m} кикнул {target_m}."


async def handle_voluntary_leave(
    api: API,
    peer_id: int,
    user_id: int,
) -> list[ChatNotice]:
    settings = await ChatSettingsRepository.get(peer_id)
    if settings.rejoin_kick == GuardMode.OFF:
        return []

    names = DisplayNameService(api)
    moderation = ModerationService(api)
    link = await names.link_user(user_id)
    notices: list[ChatNotice] = []

    if settings.rejoin_kick == GuardMode.ASK:
        notices.append(
            await build_rejoinkick_ask_leave(api, peer_id=peer_id, target_id=user_id)
        )
        return notices

    await _kick_on_leave(moderation, peer_id, user_id)
    notices.append(ChatNotice(text=f"🚫 {link} исключён при выходе из беседы."))
    return notices


async def handle_member_joined(
    *,
    api: API,
    peer_id: int,
    invited_id: int,
) -> list[ChatNotice]:
    if invited_id <= 0 or peer_id < 2_000_000_000:
        return []

    settings = await ChatSettingsRepository.get(peer_id)
    if settings.rejoin_kick == GuardMode.OFF:
        await ChatSettingsRepository.clear_left_record(peer_id, invited_id)
        return []

    if not await ChatSettingsRepository.was_voluntary_leave(peer_id, invited_id):
        return []

    names = DisplayNameService(api)
    moderation = ModerationService(api)
    invited_link = await names.link_user(invited_id)
    notices: list[ChatNotice] = []

    if settings.rejoin_kick == GuardMode.ASK:
        notices.append(
            await build_rejoinkick_ask_rejoin(
                api, peer_id=peer_id, target_id=invited_id
            )
        )
        return notices

    result = await moderation.kick_from_chat(peer_id, invited_id)
    if result.success:
        await ChatSettingsRepository.clear_left_record(peer_id, invited_id)
        notices.append(
            ChatNotice(
                text=f"🚫 {invited_link} исключён: повторный вход после выхода."
            )
        )
    else:
        notices.append(
            ChatNotice(
                text=(
                    f"❌ Не удалось исключить {invited_link}: "
                    f"{result.error or 'нет прав у бота'}"
                )
            )
        )
    return notices
