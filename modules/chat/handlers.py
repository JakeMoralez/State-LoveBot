"""Участники беседы: /members, приветствие, автоснятие ролей, guard при входе."""

from __future__ import annotations

import json
import logging

from vkbottle import API, GroupEventType
from vkbottle.bot import Bot, Message, MessageEvent

from database.models.user import AccessLevel
from database.repository.chat_settings_repo import ChatSettingsRepository
from middlewares.access import AccessChecker, requires_level, requires_public
from services.chat_events import parse_chat_member_event
from middlewares.action_logger import ActionLogger
from services.command_utils import dual
from services.invite_guard import (
    ChatNotice,
    format_rejoinkick_action_message,
    handle_member_joined,
    handle_voluntary_leave,
)
from services.messaging import MessagingService
from services.moderation import ModerationService
from services.ca_access import handle_sled_ca_join, handle_sled_ca_leave
from services.random_reactions import maybe_add_reaction
from services.role_chat_leave import handle_role_chat_leave

logger = logging.getLogger(__name__)


def register_chat(bot: Bot, api: API, action_logger: ActionLogger) -> None:
    messaging = MessagingService(api)
    moderation = ModerationService(api)

    async def _send_notice(peer_id: int, notice: ChatNotice) -> None:
        kwargs: dict = {
            "peer_id": peer_id,
            "message": notice.text,
            "random_id": messaging.random_id(),
            "disable_mentions": 1,
        }
        if notice.keyboard:
            kwargs["keyboard"] = notice.keyboard
        await api.messages.send(**kwargs)

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

    @bot.on.message(text=dual("del"))
    @requires_level(AccessLevel.SUPERVISOR)
    async def delete_message(
        message: Message,
        server_id: int = 0,
        access_level: int = 0,
    ) -> None:
        if message.peer_id < 2_000_000_000:
            await message.answer("❌ Команда доступна только в беседах.")
            return
        if not message.reply_message:
            await message.answer("❌ Ответьте на сообщение, которое нужно удалить.")
            return

        cmid = message.reply_message.conversation_message_id
        if not cmid:
            await message.answer("❌ Не удалось определить ID сообщения.")
            return

        try:
            await api.messages.delete(
                peer_id=message.peer_id,
                cmids=[cmid],
                delete_for_all=True,
            )
            await action_logger.log_user(
                "delete_message",
                message.from_id,
                f"cmid {cmid}",
                "Удалено",
                source_peer_id=message.peer_id,
            )
        except Exception as exc:
            logger.error("delete failed peer=%s cmid=%s: %s", message.peer_id, cmid, exc)
            await message.answer(f"❌ Не удалось удалить: {exc}")

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

    async def _notify_member_left(
        peer_id: int,
        user_id: int,
        *,
        voluntary: bool,
    ) -> None:
        try:
            notices: list[str] = []
            role_notice: str | None = None
            role_notice = await handle_role_chat_leave(peer_id, user_id, api)
            if role_notice:
                notices.append(role_notice)
            sled_notice = await handle_sled_ca_leave(peer_id, user_id, api)
            if sled_notice:
                notices.append(sled_notice)
            if voluntary:
                for rejoink_notice in await handle_voluntary_leave(
                    api, peer_id, user_id
                ):
                    await _send_notice(peer_id, rejoink_notice)

            for notice in notices:
                await api.messages.send(
                    peer_id=peer_id,
                    message=notice,
                    random_id=messaging.random_id(),
                    disable_mentions=1,
                )
            if role_notice:
                await action_logger.log_user(
                    "role_leave",
                    user_id,
                    f"id{user_id}",
                    "Роли сняты",
                    source_peer_id=peer_id,
                )
        except Exception as exc:
            logger.warning("role leave notice failed peer=%s user=%s: %s", peer_id, user_id, exc)

    async def _welcome_member(peer_id: int, member_id: int) -> None:
        try:
            guard_notices = await handle_member_joined(
                api=api,
                peer_id=peer_id,
                invited_id=member_id,
            )
            if guard_notices:
                for notice in guard_notices:
                    await _send_notice(peer_id, notice)
                return
        except Exception as exc:
            logger.warning("invite guard failed peer=%s: %s", peer_id, exc)

        try:
            sled_notice = await handle_sled_ca_join(peer_id, member_id, api)
            if sled_notice:
                await api.messages.send(
                    peer_id=peer_id,
                    message=sled_notice,
                    random_id=messaging.random_id(),
                    disable_mentions=1,
                )
        except Exception as exc:
            logger.warning("sled_ca join failed peer=%s member=%s: %s", peer_id, member_id, exc)

        try:
            welcome = await messaging.format_invite_notice(member_id)
            await api.messages.send(
                peer_id=peer_id,
                message=welcome,
                random_id=messaging.random_id(),
                disable_mentions=1,
            )
        except Exception as exc:
            logger.warning("welcome failed peer=%s member=%s: %s", peer_id, member_id, exc)

    @bot.on.raw_event(GroupEventType.MESSAGE_NEW)
    async def on_random_reaction(event: dict) -> None:
        await maybe_add_reaction(api, event)

    @bot.on.raw_event(GroupEventType.MESSAGE_NEW)
    async def on_chat_member_event(event: dict) -> None:
        """Raw: выход VK = chat_kick_user (from_id==member_id), не chat_leave_user."""
        parsed = parse_chat_member_event(event)
        if not parsed:
            return

        peer_id = parsed["peer_id"]
        member_id = parsed["member_id"]
        kind = parsed["kind"]

        logger.info(
            "chat event peer=%s user=%s kind=%s action=%s",
            peer_id,
            member_id,
            kind,
            parsed["action_type"],
        )

        if kind == "join":
            await _welcome_member(peer_id, member_id)
        elif kind == "leave_voluntary":
            await _notify_member_left(peer_id, member_id, voluntary=True)
        elif kind == "leave_kicked":
            await _notify_member_left(peer_id, member_id, voluntary=False)

    @bot.on.raw_event(GroupEventType.MESSAGE_EVENT, MessageEvent)
    async def rejoinkick_kick_callback(event: MessageEvent) -> None:
        payload = event.payload
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                return
        if not isinstance(payload, dict) or payload.get("cmd") != "rejoinkick_kick":
            return

        try:
            peer_id = int(payload["peer_id"])
            target_id = int(payload["target_id"])
        except (KeyError, TypeError, ValueError):
            await event.show_snackbar("❌ Некорректный запрос.")
            return

        if event.peer_id != peer_id or peer_id < 2_000_000_000 or target_id <= 0:
            await event.show_snackbar("❌ Некорректный запрос.")
            return

        server_id = await AccessChecker.resolve_server_id(peer_id)
        if await AccessChecker.get_level(event.user_id, server_id) < AccessLevel.SUPERVISOR:
            await event.show_snackbar("⛔ Недостаточно прав.")
            return

        if not await ChatSettingsRepository.was_voluntary_leave(peer_id, target_id):
            await event.show_snackbar("❌ Пользователь не в списке выхода.")
            return

        result = await moderation.kick_from_chat(peer_id, target_id)
        if result.success:
            await ChatSettingsRepository.clear_left_record(peer_id, target_id)
        else:
            await ChatSettingsRepository.record_voluntary_leave(peer_id, target_id)

        text = await format_rejoinkick_action_message(
            api,
            actor_id=event.user_id,
            target_id=target_id,
        )
        await api.messages.send(
            peer_id=peer_id,
            message=text,
            random_id=messaging.random_id(),
            disable_mentions=1,
        )
        await event.send_empty_answer()
