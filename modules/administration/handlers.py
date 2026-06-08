"""Модерация: /kick, /poolkick."""

from __future__ import annotations

import logging

from vkbottle import API
from vkbottle.bot import Bot, Message

from database.models.user import AccessLevel
from database.repository.chat_repo import ChatRepository
from middlewares.access import requires_level
from middlewares.congress_access import requires_chat_kick
from middlewares.action_logger import ActionLogger
from services.command_utils import dual, dual_with_args
from services.display_name import DisplayNameService
from services.moderation import ModerationService
from services.vk_resolver import VKResolver

logger = logging.getLogger(__name__)


def _parse_target_and_reason(args: str) -> tuple[str, str | None]:
    parts = args.strip().split(maxsplit=1)
    if not parts:
        return "", None
    target = VKResolver.extract_reference(parts[0])
    return target, parts[1] if len(parts) > 1 else None


def register_administration(bot: Bot, api: API, action_logger: ActionLogger) -> None:
    moderation = ModerationService(api)
    names = DisplayNameService(api)
    resolver = VKResolver(api)

    async def _kick_announce(
        peer_id: int,
        *,
        target_id: int,
        actor_id: int,
        reason: str | None,
        pool_label: str | None = None,
    ) -> None:
        target_m = await names.link_user(target_id)
        actor_m = await names.link_user(actor_id)

        lines = [
            f"🚫 {target_m} был(а) исключён(а) по запросу {actor_m}.",
        ]
        if pool_label:
            lines.append(f"📂 Пул: {pool_label}")
        if reason:
            lines.append(f"📝 Причина: {reason}")
        try:
            await api.messages.send(
                peer_id=peer_id,
                message="\n".join(lines),
                random_id=0,
                disable_mentions=1,
            )
        except Exception as exc:
            logger.warning("kick announce failed peer=%s: %s", peer_id, exc)

    @bot.on.message(text=dual("kick"))
    @requires_level(AccessLevel.ZGS)
    async def kick_usage(
        message: Message,
        server_id: int = 0,
        access_level: int = 0,
    ) -> None:
        await message.answer(
            "❌ /kick (/k) [ссылка vk.com/vk.ru|ID|@user] [причина]\n"
            "Можно ответом на сообщение: /kick причина"
        )

    @bot.on.message(text=dual_with_args("kick", "<args>"))
    @requires_chat_kick
    async def kick(
        message: Message,
        args: str,
        server_id: int = 0,
        access_level: int = 0,
    ) -> None:
        if message.peer_id < 2_000_000_000:
            await message.answer("❌ /kick только в беседах.")
            return

        reply_id = (
            message.reply_message.from_id
            if message.reply_message and message.reply_message.from_id > 0
            else None
        )

        if reply_id:
            resolved = await resolver.resolve(str(reply_id))
            reason = args.strip() or None
        else:
            target_raw, reason = _parse_target_and_reason(args)
            resolved = await resolver.resolve(target_raw)

        if not resolved:
            await message.answer("❌ Пользователь не найден.")
            return

        chat = await ChatRepository.get_by_peer_id(message.peer_id)
        pool_id = chat.pool_id if chat else None

        result = await moderation.kick(
            server_id=server_id,
            pool_id=pool_id,
            peer_id=message.peer_id,
            actor_vk_id=message.from_id,
            target_vk_id=resolved.vk_id,
            reason=reason,
        )

        if result.success:
            await _kick_announce(
                message.peer_id,
                target_id=resolved.vk_id,
                actor_id=message.from_id,
                reason=reason,
            )
            await action_logger.log_user(
                "kick",
                message.from_id,
                f"id{resolved.vk_id}" + (f", причина: {reason}" if reason else ""),
                "Исключён",
                source_peer_id=message.peer_id,
            )
        else:
            await message.answer(
                f"❌ Не удалось исключить.\n{result.error or 'нет прав админа у бота'}"
            )
            await action_logger.log_user(
                "kick",
                message.from_id,
                f"id{resolved.vk_id}",
                f"Ошибка: {(result.error or 'нет прав')[:80]}",
                source_peer_id=message.peer_id,
            )

    @bot.on.message(text=dual("poolkick"))
    @requires_level(AccessLevel.ZGS)
    async def poolkick_usage(
        message: Message,
        server_id: int = 0,
        access_level: int = 0,
    ) -> None:
        await message.answer(
            "❌ /poolkick (/pkick) [ссылка vk.com/vk.ru|ID|@user] [причина]"
        )

    @bot.on.message(text=dual_with_args("poolkick", "<args>"))
    @requires_level(AccessLevel.ZGS)
    async def poolkick(
        message: Message,
        args: str,
        server_id: int = 0,
        access_level: int = 0,
    ) -> None:
        chat = await ChatRepository.get_by_peer_id(message.peer_id)
        if not chat or not chat.pool_id:
            await message.answer("❌ Беседа не привязана к пулу (/regchat).")
            return

        target_raw, reason = _parse_target_and_reason(args)
        reply_id = (
            message.reply_message.from_id
            if message.reply_message and message.reply_message.from_id > 0
            else None
        )
        resolved = await resolver.resolve_from_message(
            target_raw, reply_from_id=reply_id
        )
        if not resolved:
            await message.answer("❌ Пользователь не найден.")
            return

        await chat.fetch_related("pool")
        pool_name = chat.pool.name if chat.pool else str(chat.pool_id)
        report = await moderation.pullkick(
            server_id=server_id,
            pool_id=chat.pool_id,
            actor_vk_id=message.from_id,
            target_vk_id=resolved.vk_id,
            reason=reason,
        )

        for item in report.results:
            if item.success:
                await _kick_announce(
                    item.peer_id,
                    target_id=resolved.vk_id,
                    actor_id=message.from_id,
                    reason=reason,
                    pool_label=pool_name,
                )

        await message.answer(
            f"📋 Poolkick: {report.summary()}"
            + (f"\n📝 {reason}" if reason else "")
        )
        await action_logger.log_user(
            "poolkick",
            message.from_id,
            f"id{resolved.vk_id}, пул {pool_name}" + (f", {reason}" if reason else ""),
            report.summary(),
            source_peer_id=message.peer_id,
        )
