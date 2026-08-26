"""Конгресс: регистрация беседы, спикер / вице, setnick только в конференции."""

from __future__ import annotations

import logging

from vkbottle import API
from vkbottle.bot import Bot, Message

from database.models.user import AccessLevel
from database.repository.congress_repo import CONGRESS_DEFAULT_ALIAS, CongressRepository
from middlewares.access import requires_level, requires_public
from middlewares.ca_access import requires_ca_scope
from middlewares.action_logger import ActionLogger
from services.command_utils import dual, dual_args
from services.display_name import DisplayNameService
from services.staff_hierarchy import can_act_on_target
from services.vk_resolver import VKResolver

logger = logging.getLogger(__name__)


async def _assert_can_replace_officer(
    *,
    actor_id: int,
    actor_level: int,
    server_id: int,
    current_vk_id: int | None,
    role_label: str,
) -> str | None:
    """None если можно снять/заменить текущего спикера или вице."""
    if not current_vk_id:
        return None
    allowed, err = await can_act_on_target(
        actor_id,
        actor_level,
        current_vk_id,
        server_id,
        on_equal_or_higher=(
            f"❌ Нельзя снять {role_label} своего уровня или выше."
        ),
        on_developer=f"❌ Нельзя снять {role_label} у разработчика.",
    )
    if allowed:
        return None
    return err or "❌ Недостаточно прав."


async def _format_congress_info(api: API, server_id: int) -> str:
    peer_id = await CongressRepository.get_congress_peer_id(server_id)
    if not peer_id:
        return "📭 Беседа конгресса не зарегистрирована.\nИспользуйте /regrole congress в конференции."

    alias = await CongressRepository.get_congress_alias(server_id)
    names = DisplayNameService(api, server_id)
    lines = [
        "🏛 Конгресс",
        f"📌 Беседа: peer {peer_id} (chat {peer_id - 2_000_000_000})",
        f"📋 Алиас /msg: {alias or CONGRESS_DEFAULT_ALIAS}",
        "",
    ]

    speaker = await CongressRepository.get_speaker(server_id)
    if speaker:
        link = await names.link_user(speaker.vk_id, server_id)
        lines.append(f"🎙 Спикер: {link}")
    else:
        lines.append("🎙 Спикер: не назначен")

    vice = await CongressRepository.get_vice(server_id)
    if vice:
        link = await names.link_user(vice.vk_id, server_id)
        lines.append(f"🎖 Вице-спикер: {link}")
    else:
        lines.append("🎖 Вице-спикер: не назначен")

    lines.append("")
    lines.append("Спикер и вице в конфе: /setnick, /kick, /msg")
    lines.append(f"Из ЛС бота: /msg {alias or CONGRESS_DEFAULT_ALIAS} [текст]")
    return "\n".join(lines)


def register_congress(bot: Bot, api: API, action_logger: ActionLogger) -> None:
    resolver = VKResolver(api)
    names = DisplayNameService(api)

    @bot.on.message(text=dual("congress"))
    @requires_public
    async def congress_info(
        message: Message,
        server_id: int = 0,
        access_level: int = 0,
    ) -> None:
        await message.answer(
            await _format_congress_info(api, server_id),
            disable_mentions=1,
        )

    @bot.on.message(text=dual_args("setspeaker"))
    @requires_level(AccessLevel.SUPERVISOR)
    @requires_ca_scope
    async def set_speaker(
        message: Message,
        args: str | None = None,
        server_id: int = 0,
        access_level: int = 0,
    ) -> None:
        if not args and not (
            message.reply_message and message.reply_message.from_id > 0
        ):
            await message.answer(
                "❌ /setspeaker [@user]\n"
                "Или ответом на сообщение."
            )
            return

        reply_id = (
            message.reply_message.from_id
            if message.reply_message and message.reply_message.from_id > 0
            else None
        )
        target_raw = VKResolver.extract_reference(args or "")
        resolved, hint = await resolver.resolve_from_message_with_hint(
            target_raw,
            reply_from_id=reply_id,
            server_id=server_id,
        )
        if hint:
            await message.answer(hint, disable_mentions=1)
            return
        if not resolved:
            await message.answer("❌ Пользователь не найден.")
            return

        actor_id = message.from_id or 0
        current = await CongressRepository.get_speaker(server_id)
        current_id = current.vk_id if current else None
        if current_id and current_id != resolved.vk_id:
            blocked = await _assert_can_replace_officer(
                actor_id=actor_id,
                actor_level=access_level,
                server_id=server_id,
                current_vk_id=current_id,
                role_label="спикера",
            )
            if blocked:
                await message.answer(blocked)
                return

        await CongressRepository.set_speaker(
            resolved.vk_id,
            server_id,
            username=resolved.username,
            assigned_by=actor_id,
        )
        link = await names.link_user(resolved.vk_id, server_id)
        await message.answer(
            f"🎙 Спикер конгресса: {link}\n"
            f"В конфе: /setnick, /kick. /msg — конфа или ЛС бота.",
            disable_mentions=1,
        )
        await action_logger.log_user(
            "set_speaker",
            message.from_id,
            f"id{resolved.vk_id}",
            "Назначен спикером",
            source_peer_id=message.peer_id,
        )

    @bot.on.message(text=dual_args("setvice"))
    @requires_level(AccessLevel.SUPERVISOR)
    @requires_ca_scope
    async def set_vice(
        message: Message,
        args: str | None = None,
        server_id: int = 0,
        access_level: int = 0,
    ) -> None:
        if not args and not (
            message.reply_message and message.reply_message.from_id > 0
        ):
            await message.answer(
                "❌ /setvice [@user]\n"
                "Или ответом на сообщение."
            )
            return

        reply_id = (
            message.reply_message.from_id
            if message.reply_message and message.reply_message.from_id > 0
            else None
        )
        target_raw = VKResolver.extract_reference(args or "")
        resolved, hint = await resolver.resolve_from_message_with_hint(
            target_raw,
            reply_from_id=reply_id,
            server_id=server_id,
        )
        if hint:
            await message.answer(hint, disable_mentions=1)
            return
        if not resolved:
            await message.answer("❌ Пользователь не найден.")
            return

        actor_id = message.from_id or 0
        current = await CongressRepository.get_vice(server_id)
        current_id = current.vk_id if current else None
        if current_id and current_id != resolved.vk_id:
            blocked = await _assert_can_replace_officer(
                actor_id=actor_id,
                actor_level=access_level,
                server_id=server_id,
                current_vk_id=current_id,
                role_label="вице-спикера",
            )
            if blocked:
                await message.answer(blocked)
                return

        await CongressRepository.set_vice(
            resolved.vk_id,
            server_id,
            username=resolved.username,
            assigned_by=actor_id,
        )
        link = await names.link_user(resolved.vk_id, server_id)
        await message.answer(
            f"🎖 Вице-спикер конгресса: {link}\n"
            f"В конфе: /setnick, /kick. /msg — конфа или ЛС бота.",
            disable_mentions=1,
        )
        await action_logger.log_user(
            "set_vice",
            message.from_id,
            f"id{resolved.vk_id}",
            "Назначен вице-спикером",
            source_peer_id=message.peer_id,
        )

    @bot.on.message(text=dual("removespeaker"))
    @requires_level(AccessLevel.SUPERVISOR)
    @requires_ca_scope
    async def remove_speaker(
        message: Message,
        server_id: int = 0,
        access_level: int = 0,
    ) -> None:
        actor_id = message.from_id or 0
        current = await CongressRepository.get_speaker(server_id)
        blocked = await _assert_can_replace_officer(
            actor_id=actor_id,
            actor_level=access_level,
            server_id=server_id,
            current_vk_id=current.vk_id if current else None,
            role_label="спикера",
        )
        if blocked:
            await message.answer(blocked)
            return
        ok = await CongressRepository.clear_speaker(server_id)
        await message.answer("✅ Спикер снят." if ok else "❌ Спикер не был назначен.")

    @bot.on.message(text=dual("removevice"))
    @requires_level(AccessLevel.SUPERVISOR)
    @requires_ca_scope
    async def remove_vice(
        message: Message,
        server_id: int = 0,
        access_level: int = 0,
    ) -> None:
        actor_id = message.from_id or 0
        current = await CongressRepository.get_vice(server_id)
        blocked = await _assert_can_replace_officer(
            actor_id=actor_id,
            actor_level=access_level,
            server_id=server_id,
            current_vk_id=current.vk_id if current else None,
            role_label="вице-спикера",
        )
        if blocked:
            await message.answer(blocked)
            return
        ok = await CongressRepository.clear_vice(server_id)
        await message.answer("✅ Вице-спикер снят." if ok else "❌ Вице не был назначен.")
