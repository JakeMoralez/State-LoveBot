"""Участники беседы: /members, приветствие, автоснятие ролей, guard при входе."""

from __future__ import annotations

import asyncio
import json
import logging

from vkbottle import API, GroupEventType
from vkbottle.bot import Bot, Message, MessageEvent

from database.models.chat_settings import GuardMode
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
from services.display_name import DisplayNameService
from services.messaging import MessagingService
from services.moderation import ModerationService
from services.ca_access import handle_sled_ca_join, handle_sled_ca_leave
from services.chat_admin import ChatAdminService
from services.leader_access import handle_leader_chat_join
from services.random_reactions import maybe_add_reaction
from services.role_chat_leave import handle_role_chat_leave

logger = logging.getLogger(__name__)


def register_chat(bot: Bot, api: API, action_logger: ActionLogger) -> None:
    messaging = MessagingService(api)
    moderation = ModerationService(api)
    chat_admin = ChatAdminService(api)

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

        target_cmids: list[int] = []
        seen: set[int] = set()

        def _add_cmid(raw: object) -> None:
            try:
                cmid = int(raw)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                return
            if cmid > 0 and cmid not in seen:
                seen.add(cmid)
                target_cmids.append(cmid)

        if message.reply_message:
            _add_cmid(message.reply_message.conversation_message_id)

        for fwd in message.fwd_messages or []:
            _add_cmid(getattr(fwd, "conversation_message_id", None))

        if not target_cmids:
            await message.answer(
                "❌ Ответьте на сообщение(я) или перешлите их с командой /del."
            )
            return

        delete_cmids = list(target_cmids)
        cmd_cmid = message.conversation_message_id
        if cmd_cmid:
            try:
                cmd_cmid_int = int(cmd_cmid)
            except (TypeError, ValueError):
                cmd_cmid_int = 0
            if cmd_cmid_int > 0 and cmd_cmid_int not in seen:
                delete_cmids.append(cmd_cmid_int)

        try:
            await api.messages.delete(
                peer_id=message.peer_id,
                cmids=delete_cmids,
                delete_for_all=True,
            )
        except Exception as exc:
            logger.error(
                "delete failed peer=%s cmids=%s: %s",
                message.peer_id,
                delete_cmids,
                exc,
            )
            await message.answer(f"❌ Не удалось удалить: {exc}")
            return

        n = len(target_cmids)
        if n % 10 == 1 and n % 100 != 11:
            word = "сообщение"
        elif 2 <= n % 10 <= 4 and not (12 <= n % 100 <= 14):
            word = "сообщения"
        else:
            word = "сообщений"

        actor_link = await DisplayNameService(api, server_id).link_user(
            message.from_id or 0
        )
        await api.messages.send(
            peer_id=message.peer_id,
            message=f"🗑 {actor_link} удалил(а) {n} {word}.",
            random_id=messaging.random_id(),
            disable_mentions=1,
        )
        await action_logger.log_user(
            "delete_message",
            message.from_id,
            f"{n} сообщ.",
            "Удалено",
            source_peer_id=message.peer_id,
        )
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

    async def _send_text(peer_id: int, text: str) -> None:
        await api.messages.send(
            peer_id=peer_id,
            message=text,
            random_id=messaging.random_id(),
            disable_mentions=1,
        )

    async def _notify_member_left(
        peer_id: int,
        user_id: int,
        *,
        voluntary: bool,
        actor_id: int | None = None,
    ) -> None:
        try:
            notices: list[str] = []
            role_notice: str | None = None

            settings = await ChatSettingsRepository.get(peer_id)
            server_id = await AccessChecker.resolve_server_id(peer_id)
            names = DisplayNameService(api, server_id)
            target_link = await names.link_user(user_id)

            if voluntary:
                leave_mode = ChatSettingsRepository.effective_kick_on_leave(settings)
                if leave_mode == GuardMode.OFF:
                    notices.append(f"➖ {target_link} покинул(а) беседу.")
            elif actor_id and actor_id > 0 and actor_id != user_id:
                actor_link = await names.link_user(actor_id)
                notices.append(f"🚫 {actor_link} исключил(а) {target_link}.")
            else:
                notices.append(f"🚫 {target_link} исключён(а) из беседы.")

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
                await _send_text(peer_id, notice)
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

    async def _apply_auto_mute_on_join(peer_id: int, member_id: int) -> None:
        try:
            settings = await ChatSettingsRepository.get(peer_id)
            if settings.auto_mute_on_join != GuardMode.ON:
                return
            await asyncio.sleep(2)
            ok, err = await chat_admin.mute_member(peer_id, member_id, seconds=None)
            if not ok:
                await asyncio.sleep(3)
                ok, err = await chat_admin.mute_member(peer_id, member_id, seconds=None)
            if not ok:
                logger.warning(
                    "auto_mute_on_join failed peer=%s user=%s: %s",
                    peer_id,
                    member_id,
                    err,
                )
        except Exception as exc:
            logger.warning(
                "auto_mute_on_join peer=%s member=%s: %s", peer_id, member_id, exc
            )

    async def _welcome_member(
        peer_id: int,
        member_id: int,
        *,
        actor_id: int | None = None,
    ) -> None:
        invited_by = (
            actor_id
            if actor_id and actor_id > 0 and actor_id != member_id
            else None
        )

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

        asyncio.create_task(_apply_auto_mute_on_join(peer_id, member_id))

        try:
            sled_notice = await handle_sled_ca_join(peer_id, member_id, api)
            if sled_notice:
                await _send_text(peer_id, sled_notice)
        except Exception as exc:
            logger.warning("sled_ca join failed peer=%s member=%s: %s", peer_id, member_id, exc)

        try:
            await handle_leader_chat_join(peer_id, member_id, api)
        except Exception as exc:
            logger.warning("leader join failed peer=%s member=%s: %s", peer_id, member_id, exc)

        try:
            server_id = await AccessChecker.resolve_server_id(peer_id)
            welcome = await messaging.format_welcome_notice(
                member_id,
                invited_by=invited_by,
                server_id=server_id,
            )
            await _send_text(peer_id, welcome)
        except Exception as exc:
            logger.warning("welcome failed peer=%s member=%s: %s", peer_id, member_id, exc)

    @bot.on.raw_event(GroupEventType.MESSAGE_NEW, blocking=False)
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
        actor_id = parsed.get("actor_id")
        kind = parsed["kind"]

        logger.info(
            "chat event peer=%s user=%s actor=%s kind=%s action=%s",
            peer_id,
            member_id,
            actor_id,
            kind,
            parsed["action_type"],
        )

        if kind == "join":
            await _welcome_member(peer_id, member_id, actor_id=actor_id)
        elif kind == "leave_voluntary":
            await _notify_member_left(
                peer_id, member_id, voluntary=True, actor_id=actor_id
            )
        elif kind == "leave_kicked":
            await _notify_member_left(
                peer_id, member_id, voluntary=False, actor_id=actor_id
            )

    @bot.on.raw_event(GroupEventType.MESSAGE_EVENT, MessageEvent, blocking=False)
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

        server_id = await AccessChecker.resolve_server_id(peer_id, event.user_id)
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
