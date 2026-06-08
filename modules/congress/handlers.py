"""Конгресс: регистрация беседы, спикер / вице, setnick только в конференции."""

from __future__ import annotations

import logging

from vkbottle import API
from vkbottle.bot import Bot, Message

from database.models.user import AccessLevel
from database.repository.congress_repo import CONGRESS_DEFAULT_ALIAS, CongressRepository
from middlewares.access import requires_level
from middlewares.action_logger import ActionLogger
from services.command_utils import dual, dual_args, dual_with_args
from services.display_name import DisplayNameService
from services.vk_resolver import VKResolver

logger = logging.getLogger(__name__)


async def _format_congress_info(api: API, server_id: int) -> str:
    peer_id = await CongressRepository.get_congress_peer_id()
    if not peer_id:
        return "📭 Беседа конгресса не зарегистрирована.\nИспользуйте /regcongress в конференции."

    alias = await CongressRepository.get_congress_alias(server_id)
    names = DisplayNameService(api)
    lines = [
        "🏛 Конгресс",
        f"📌 Беседа: peer {peer_id} (chat {peer_id - 2_000_000_000})",
        f"📋 Алиас /msg: {alias or CONGRESS_DEFAULT_ALIAS}",
        "",
    ]

    speaker = await CongressRepository.get_speaker()
    if speaker:
        link = await names.link_user(speaker.vk_id)
        lines.append(f"🎙 Спикер: {link}")
    else:
        lines.append("🎙 Спикер: не назначен")

    vice = await CongressRepository.get_vice()
    if vice:
        link = await names.link_user(vice.vk_id)
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

    async def _register_congress_chat(
        message: Message,
        server_id: int,
        alias: str | None = None,
    ) -> None:
        if message.peer_id < 2_000_000_000:
            await message.answer("❌ Регистрация только в беседе конференции.")
            return

        title = None
        try:
            conv = await api.messages.get_conversations_by_id(peer_ids=[message.peer_id])
            if conv.items:
                title = conv.items[0].chat_settings.title
        except Exception as exc:
            logger.warning("Не удалось получить название беседы конгресса: %s", exc)

        try:
            normalized = await CongressRepository.register_chat(
                message.peer_id,
                message.from_id or 0,
                server_id,
                alias=alias,
                title=title,
            )
        except ValueError as exc:
            await message.answer(f"❌ {exc}")
            return

        await message.answer(
            f"✅ Беседа конгресса привязана.\n"
            f"Алиас /msg: {normalized}\n"
            f"Спикер и вице: /setnick, /kick, /msg {normalized} — только здесь "
            f"(или /msg из ЛС бота).\n"
            f"Назначение: /setspeaker, /setvice"
        )
        await action_logger.log_user(
            "regcongress",
            message.from_id,
            f"peer {message.peer_id}, алиас {normalized}",
            "Беседа конгресса привязана",
            source_peer_id=message.peer_id,
        )

    @bot.on.message(text=dual("regcongress"))
    @requires_level(AccessLevel.ZGS)
    async def reg_congress(
        message: Message,
        server_id: int = 0,
        access_level: int = 0,
    ) -> None:
        await _register_congress_chat(message, server_id)

    @bot.on.message(text=dual_with_args("regcongress", "<alias>"))
    @requires_level(AccessLevel.ZGS)
    async def reg_congress_alias(
        message: Message,
        alias: str,
        server_id: int = 0,
        access_level: int = 0,
    ) -> None:
        await _register_congress_chat(message, server_id, alias=alias)

    @bot.on.message(text=dual("congress"))
    @requires_level(AccessLevel.PGS, require_registered=True)
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
    @requires_level(AccessLevel.ZGS)
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
                "❌ /setspeaker [@user|vk.com|vk.ru]\n"
                "Или ответом на сообщение кандидата."
            )
            return

        reply_id = (
            message.reply_message.from_id
            if message.reply_message and message.reply_message.from_id > 0
            else None
        )
        target_raw = VKResolver.extract_reference(args or "")
        resolved = await resolver.resolve_from_message(
            target_raw, reply_from_id=reply_id
        )
        if not resolved:
            await message.answer("❌ Пользователь не найден.")
            return

        await CongressRepository.set_speaker(
            resolved.vk_id,
            username=resolved.username,
            assigned_by=message.from_id or 0,
        )
        link = await names.link_user(resolved.vk_id)
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
    @requires_level(AccessLevel.ZGS)
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
                "❌ /setvice [@user|vk.com|vk.ru]\n"
                "Или ответом на сообщение кандидата."
            )
            return

        reply_id = (
            message.reply_message.from_id
            if message.reply_message and message.reply_message.from_id > 0
            else None
        )
        target_raw = VKResolver.extract_reference(args or "")
        resolved = await resolver.resolve_from_message(
            target_raw, reply_from_id=reply_id
        )
        if not resolved:
            await message.answer("❌ Пользователь не найден.")
            return

        await CongressRepository.set_vice(
            resolved.vk_id,
            username=resolved.username,
            assigned_by=message.from_id or 0,
        )
        link = await names.link_user(resolved.vk_id)
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
    @requires_level(AccessLevel.ZGS)
    async def remove_speaker(
        message: Message,
        server_id: int = 0,
        access_level: int = 0,
    ) -> None:
        ok = await CongressRepository.clear_speaker()
        await message.answer("✅ Спикер снят." if ok else "❌ Спикер не был назначен.")

    @bot.on.message(text=dual("removevice"))
    @requires_level(AccessLevel.ZGS)
    async def remove_vice(
        message: Message,
        server_id: int = 0,
        access_level: int = 0,
    ) -> None:
        ok = await CongressRepository.clear_vice()
        await message.answer("✅ Вице-спикер снят." if ok else "❌ Вице не был назначен.")
