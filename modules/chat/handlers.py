"""Участники беседы: /members, приветствие, автоснятие ролей."""

from __future__ import annotations

import logging

from vkbottle import API
from vkbottle.bot import Bot, Message

from database.models.user import AccessLevel
from middlewares.access import requires_level, requires_public
from middlewares.action_logger import ActionLogger
from services.command_utils import dual
from services.messaging import MessagingService
from services.role_chat_leave import handle_role_chat_leave

logger = logging.getLogger(__name__)


def register_chat(bot: Bot, api: API, action_logger: ActionLogger) -> None:
    messaging = MessagingService(api)

    @bot.on.message(text=dual("members") + ["/chatlist", "!chatlist"])
    @requires_public
    async def list_members(
        message: Message,
        server_id: int = 0,
        access_level: int = 0,
    ) -> None:
        if message.peer_id < 2_000_000_000:
            await message.answer("❌ Команда доступна только в беседах.")
            return

        text = await messaging.format_members_list(message.peer_id, server_id)
        await message.answer(text, disable_mentions=1)

    @bot.on.message(text=["/pin", "!pin"])
    @requires_level(AccessLevel.SUPERVISOR)
    async def pin_message(
        message: Message,
        server_id: int = 0,
        access_level: int = 0,
    ) -> None:
        if message.peer_id < 2_000_000_000:
            await message.answer("❌ Команда доступна только в беседах.")
            return
        if not message.reply_message:
            await message.answer("❌ Ответьте на сообщение, которое нужно закрепить.")
            return

        cmid = message.reply_message.conversation_message_id
        if not cmid:
            await message.answer("❌ Не удалось определить ID сообщения.")
            return

        try:
            await api.messages.pin(peer_id=message.peer_id, cmid=cmid)
            await message.answer("📌 Сообщение закреплено.")
            await action_logger.log_user(
                "pin_message",
                message.from_id,
                f"cmid {cmid}",
                "Закреплено",
                source_peer_id=message.peer_id,
            )
        except Exception as exc:
            logger.error("pin failed peer=%s: %s", message.peer_id, exc)
            await message.answer(f"❌ Не удалось закрепить: {exc}")

    @bot.on.message(text=["/unpin", "!unpin"])
    @requires_level(AccessLevel.SUPERVISOR)
    async def unpin_message(
        message: Message,
        server_id: int = 0,
        access_level: int = 0,
    ) -> None:
        if message.peer_id < 2_000_000_000:
            await message.answer("❌ Команда доступна только в беседах.")
            return
        if not message.reply_message:
            await message.answer("❌ Ответьте на сообщение, которое нужно открепить.")
            return

        cmid = message.reply_message.conversation_message_id
        if not cmid:
            await message.answer("❌ Не удалось определить ID сообщения.")
            return

        try:
            await api.messages.unpin(peer_id=message.peer_id, cmid=cmid)
            await message.answer("📌 Сообщение откреплено.")
            await action_logger.log_user(
                "unpin_message",
                message.from_id,
                f"cmid {cmid}",
                "Откреплено",
                source_peer_id=message.peer_id,
            )
        except Exception as exc:
            logger.error("unpin failed peer=%s: %s", message.peer_id, exc)
            await message.answer(f"❌ Не удалось открепить: {exc}")

    async def _notify_member_left(peer_id: int, user_id: int) -> None:
        try:
            notice = await handle_role_chat_leave(peer_id, user_id, api)
            if notice:
                await api.messages.send(
                    peer_id=peer_id,
                    message=notice,
                    random_id=messaging.random_id(),
                    disable_mentions=1,
                )
                await action_logger.log_user(
                    "remove_judge",
                    user_id,
                    f"id{user_id}",
                    "Снят (выход из беседы судей)",
                    source_peer_id=peer_id,
                )
        except Exception as exc:
            logger.warning("role leave notice failed peer=%s user=%s: %s", peer_id, user_id, exc)

    @bot.on.message(action="chat_invite_user")
    async def on_user_invited(message: Message) -> None:
        if message.peer_id < 2_000_000_000:
            return
        if not message.action or not message.action.member_id:
            return
        invited_id = message.action.member_id
        if invited_id <= 0:
            return

        try:
            notice = await messaging.format_invite_notice(invited_id)
            await api.messages.send(
                peer_id=message.peer_id,
                message=notice,
                random_id=messaging.random_id(),
                disable_mentions=1,
            )
        except Exception as exc:
            logger.warning("invite notice failed peer=%s: %s", message.peer_id, exc)

    @bot.on.message(action=["chat_leave_user", "chat_kick_user"])
    async def on_user_left(message: Message) -> None:
        if message.peer_id < 2_000_000_000:
            return
        if not message.action or not message.action.member_id:
            return
        member_id = message.action.member_id
        if member_id <= 0:
            return
        await _notify_member_left(message.peer_id, member_id)
