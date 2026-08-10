"""Управление пулами: /regchat, /createpool, /msg."""

from __future__ import annotations

import json
import logging

from vkbottle import API, GroupEventType
from vkbottle.bot import Bot, Message, MessageEvent

from config.settings import VK_USER_TOKEN
from database.models.user import AccessLevel
from database.repository.chat_repo import ChatRepository
from database.repository.server_repo import ServerRepository
from database.repository.congress_repo import CongressRepository
from database.repository.forum_role_repo import ForumRoleRepository
from database.repository.pool_repo import PoolRepository
from database.repository.user_repo import UserRepository
from middlewares.access import AccessChecker, requires_developer, requires_level
from middlewares.congress_access import requires_msg
from middlewares.action_logger import ActionLogger
from services.command_utils import dual, dual_args, dual_with_args, strip_cmd
from services.messaging import MessagingService
from services.msg_keyboard import create_msg_confirm_keyboard
from services.msg_pending import pop as pop_pending_msg
from services.msg_pending import create as create_pending_msg

logger = logging.getLogger(__name__)


async def _format_congress_msg_help(server_id: int, *, header: str) -> str:
    alias = await CongressRepository.get_congress_alias(server_id)
    if not alias:
        return f"{header}\n\n❌ Беседа конгресса не зарегистрирована."
    return (
        f"{header}\n\n"
        f"📋 Алиас конгресса: {alias}\n"
        f"Пример: /msg {alias} на заседание заходим\n\n"
        f"💡 Можно из беседы конгресса или из ЛС бота."
    )


async def _format_aliases_message(server_id: int, *, header: str) -> str:
    aliases = await ChatRepository.list_aliases(server_id)
    names = [c.alias for c in aliases if c.alias]
    lines = [header, ""]
    if names:
        lines.append("📋 Доступные алиасы:")
        lines.extend(f"• {name}" for name in names)
    else:
        lines.append("📋 Алиасы не зарегистрированы. Сначала: /regchat [пул] [алиас]")
    lines.extend(["", "Пример: /msg lead_gos на собрание заходим"])
    return "\n".join(lines)


async def _resolve_pool(server_id: int, pool_ref: str):
    pool_ref = pool_ref.strip()
    if pool_ref.isdigit():
        pool = await PoolRepository.get_by_number(server_id, int(pool_ref))
        if not pool:
            pool = await PoolRepository.get_by_id(int(pool_ref))
    else:
        pool = await PoolRepository.get_by_name(server_id, pool_ref)
    if pool and pool.server_id == server_id:
        return pool
    return None


def _format_msg_preview(
    *,
    alias: str,
    target_title: str | None,
    text: str,
    preview_body: str,
    attachments: str | None = None,
) -> str:
    chat_label = f"«{alias}» ({target_title or 'беседа'})"
    lines = [
        "📋 Предпросмотр оповещения",
        "━━━━━━━━━━━━━━━━",
        f"📂 Беседа: {chat_label}",
        f"📝 Текст: {text}",
    ]
    attach_label = MessagingService.attachment_preview_label(attachments)
    if attach_label:
        lines.append(attach_label)
    lines.extend(
        [
            "",
            "Так увидят участники:",
            "━━━━━━━━━━━━━━━━",
            preview_body,
            "",
            "👇 Подтвердите отправку:",
        ]
    )
    return "\n".join(lines)


async def _can_use_msg(user_id: int, peer_id: int) -> tuple[bool, int, str]:
    if not user_id or user_id <= 0:
        return False, 0, ""
    server_id = await AccessChecker.resolve_server_id(peer_id, user_id)
    if await CongressRepository.can_use_msg(peer_id, user_id, server_id):
        return True, server_id, "congress"
    if not await ForumRoleRepository.can_use_forum_bot(user_id):
        return False, server_id, ""
    level = await AccessChecker.get_level(user_id, server_id)
    if level < AccessLevel.PGS and not await UserRepository.is_developer(user_id):
        return False, server_id, ""
    return True, server_id, "pgs"


async def _resolve_msg_target(
    server_id: int,
    alias: str,
    *,
    msg_mode: str,
) -> tuple[object | None, str | None]:
    if msg_mode == "congress":
        congress_alias = await CongressRepository.get_congress_alias(server_id)
        if not congress_alias:
            return None, "❌ Беседа конгресса не зарегистрирована."
        ok, normalized = ChatRepository.validate_alias(alias)
        if not ok or normalized != congress_alias:
            return None, await _format_congress_msg_help(
                server_id,
                header=f"❌ Доступен только алиас «{congress_alias}».",
            )
        target = await ChatRepository.get_by_alias(server_id, congress_alias)
        if not target:
            return None, await _format_congress_msg_help(
                server_id,
                header=f"❌ Беседа с алиасом «{congress_alias}» не найдена.",
            )
        return target, None

    target = await ChatRepository.get_by_alias(server_id, alias)
    if not target:
        return None, await _format_aliases_message(
            server_id,
            header=f"❌ Беседа с алиасом «{alias}» не найдена.",
        )
    return target, None


def register_pools(bot: Bot, api: API, action_logger: ActionLogger) -> None:
    user_api = API(token=VK_USER_TOKEN) if VK_USER_TOKEN else None
    messaging = MessagingService(api, user_api=user_api)

    async def _send_pool_alert(
        *,
        sender_id: int,
        server_id: int,
        source_peer_id: int,
        alias: str,
        target_peer_id: int,
        target_title: str | None,
        text: str,
        send_body: str,
        attachments: str | None = None,
    ) -> None:
        try:
            params: dict = {
                "peer_id": target_peer_id,
                "message": send_body,
                "random_id": messaging.random_id(),
                "disable_mentions": 0,
            }
            if attachments:
                params["attachment"] = attachments
            await api.messages.send(**params)
            await api.messages.send(
                peer_id=source_peer_id,
                message=(
                    f"✅ Оповещение отправлено в «{alias}» "
                    f"({target_title or target_peer_id})."
                ),
                random_id=messaging.random_id(),
            )
            await action_logger.log_user(
                "pool_msg",
                sender_id,
                f"алиас {alias}: {text[:80]}",
                "Отправлено",
                source_peer_id=source_peer_id,
            )
        except Exception as exc:
            logger.error("msg send failed: %s", exc)
            await api.messages.send(
                peer_id=source_peer_id,
                message=f"❌ Не удалось отправить: {exc}",
                random_id=messaging.random_id(),
            )
            await action_logger.log_user(
                "pool_msg",
                sender_id,
                f"алиас {alias}",
                f"Ошибка: {str(exc)[:80]}",
                source_peer_id=source_peer_id,
            )

    @bot.on.message(text=dual("pools"))
    @requires_level(AccessLevel.PGS)
    async def list_pools(
        message: Message,
        server_id: int = 0,
        access_level: int = 0,
    ) -> None:
        pools = await PoolRepository.list_by_server(server_id)
        if not pools:
            await message.answer("📭 Пулы на этом сервере ещё не созданы.")
            return
        lines = ["📂 Пулы бесед сервера:", ""]
        for pool in pools:
            chats = await ChatRepository.list_by_pool(pool.id)
            num = PoolRepository.display_number(pool)
            lines.append(f"• [{num}] {pool.name} — {len(chats)} бесед(ы)")
            for chat in chats:
                alias = chat.alias or "—"
                title = chat.title or f"peer {chat.peer_id}"
                lines.append(f"    └ {alias}: {title}")
        await message.answer("\n".join(lines))

    @bot.on.message(text=dual("createpool"))
    @requires_level(AccessLevel.ZGS_GOS)
    async def create_pool_usage(
        message: Message,
        server_id: int = 0,
        access_level: int = 0,
    ) -> None:
        await message.answer("❌ Использование: /createpool [название]")

    @bot.on.message(text=dual_with_args("createpool", "<name>"))
    @requires_level(AccessLevel.ZGS_GOS)
    async def create_pool(
        message: Message,
        name: str,
        server_id: int = 0,
        access_level: int = 0,
    ) -> None:
        name = name.strip()
        if not name:
            await message.answer("❌ Укажите название пула.")
            return
        existing = await PoolRepository.get_by_name(server_id, name)
        if existing:
            num = PoolRepository.display_number(existing)
            await message.answer(f"⚠️ Пул «{name}» уже существует (№ {num}).")
            return
        pool = await PoolRepository.create(
            server_id=server_id,
            name=name,
            created_by=message.from_id,
        )
        num = PoolRepository.display_number(pool)
        await message.answer(f"✅ Пул «{pool.name}» создан (№ {num}).")
        await action_logger.log_user(
            "create_pool",
            message.from_id,
            f"«{pool.name}» (№ {num})",
            "Создан",
            source_peer_id=message.peer_id,
        )

    @bot.on.message(text=dual("regchat"))
    @requires_level(AccessLevel.ZGS_GOS)
    async def regchat_usage(
        message: Message,
        server_id: int = 0,
        access_level: int = 0,
    ) -> None:
        await message.answer(
            "❌ Использование: /regchat [ID/название пула] [алиас]\n"
            "Пример: /regchat 1 court\n"
            "Алиасы: court, lead_co, lead_gos, ruk_gos и т.д.\n"
            "Ур. 10: /devhelp — /regchat logs"
        )

    @bot.on.message(text=dual_with_args("regchat", "logs off"))
    @requires_developer
    async def regchat_logs_off(
        message: Message,
        server_id: int = 0,
        access_level: int = 0,
    ) -> None:
        if message.peer_id < 2_000_000_000:
            await message.answer("❌ Команда доступна только в беседах.")
            return

        current = await ServerRepository.get_log_peer_id(server_id)
        if current != message.peer_id:
            await message.answer("❌ Эта беседа не зарегистрирована как logs.")
            return

        await ServerRepository.set_log_peer(server_id, None)
        await message.answer(
            "✅ Беседа логов отвязана.\n"
            "Логи снова уходят в ЛС (MAIN_ADMIN_ID / LOG_CHAT_ID)."
        )
        await action_logger.log_user(
            "regchat_logs",
            message.from_id,
            f"peer {message.peer_id}",
            "Отвязана",
            source_peer_id=message.peer_id,
        )

    @bot.on.message(text=dual_with_args("regchat", "logs"))
    @requires_developer
    async def regchat_logs(
        message: Message,
        server_id: int = 0,
        access_level: int = 0,
    ) -> None:
        if message.peer_id < 2_000_000_000:
            await message.answer("❌ Команда доступна только в беседах.")
            return

        title = None
        try:
            conv = await api.messages.get_conversations_by_id(peer_ids=[message.peer_id])
            if conv.items:
                title = conv.items[0].chat_settings.title
        except Exception as exc:
            logger.warning("Не удалось получить название беседы логов: %s", exc)

        await ChatRepository.register_chat(
            peer_id=message.peer_id,
            server_id=server_id,
            pool_id=None,
            alias=None,
            title=title,
            registered_by=message.from_id,
        )
        await ServerRepository.set_log_peer(server_id, message.peer_id)
        await message.answer(
            f"✅ Беседа «{title or message.peer_id}» — канал логов.\n"
            "Все действия бота пишутся сюда."
        )
        await action_logger.log_user(
            "regchat_logs",
            message.from_id,
            f"peer {message.peer_id}",
            "Зарегистрирована",
            source_peer_id=message.peer_id,
        )

    @bot.on.message(text=dual_with_args("regchat", "<pool_ref> <alias>"))
    @requires_level(AccessLevel.ZGS_GOS)
    async def regchat(
        message: Message,
        pool_ref: str,
        alias: str,
        server_id: int = 0,
        access_level: int = 0,
    ) -> None:
        if message.peer_id < 2_000_000_000:
            await message.answer("❌ Команда доступна только в беседах.")
            return

        pool = await _resolve_pool(server_id, pool_ref)
        if not pool:
            await message.answer("❌ Пул не найден. Список: /pools")
            return

        ok, alias_result = ChatRepository.validate_alias(alias)
        if not ok:
            await message.answer(f"❌ {alias_result}")
            return

        existing = await ChatRepository.get_by_alias(server_id, alias_result)
        if existing and existing.peer_id != message.peer_id:
            await message.answer(f"❌ Алиас «{alias_result}» уже занят другой беседой.")
            return

        title = None
        try:
            conv = await api.messages.get_conversations_by_id(peer_ids=[message.peer_id])
            if conv.items:
                title = conv.items[0].chat_settings.title
        except Exception as exc:
            logger.warning("Не удалось получить название беседы: %s", exc)

        chat = await ChatRepository.register_chat(
            peer_id=message.peer_id,
            server_id=server_id,
            pool_id=pool.id,
            alias=alias_result,
            title=title,
            registered_by=message.from_id,
        )
        await message.answer(
            f"✅ Беседа «{title or chat.peer_id}» зарегистрирована.\n"
            f"Пул: {pool.name} (№ {PoolRepository.display_number(pool)})\n"
            f"Алиас: {chat.alias}"
        )
        await action_logger.log_user(
            "regchat",
            message.from_id,
            f"пул {pool.name}, алиас {chat.alias}",
            "Зарегистрирована",
            source_peer_id=message.peer_id,
        )

    @bot.on.message(text=dual("unregchat"))
    @requires_level(AccessLevel.ZGS_GOS)
    async def unregchat(
        message: Message,
        server_id: int = 0,
        access_level: int = 0,
    ) -> None:
        if message.peer_id < 2_000_000_000:
            await message.answer("❌ Команда доступна только в беседах.")
            return

        chat = await ChatRepository.unlink_from_pool(message.peer_id)
        if not chat:
            await message.answer("❌ Беседа не привязана к пулу.")
            return

        await message.answer(
            f"✅ Беседа отвязана от пула.\n"
            f"Алиас снят. Peer: {chat.peer_id}"
        )
        await action_logger.log_user(
            "unregchat",
            message.from_id,
            f"peer {message.peer_id}",
            "Отвязана от пула",
            source_peer_id=message.peer_id,
        )

    @bot.on.message(text=dual_args("msg"))
    @requires_msg
    async def pool_msg(
        message: Message,
        args: str | None = None,
        server_id: int = 0,
        access_level: int = 0,
        msg_mode: str = "pgs",
    ) -> None:
        raw = strip_cmd(message.text or "", "msg").strip()
        attachments = MessagingService.extract_photo_attachments(message)

        if not raw:
            if msg_mode == "congress":
                await message.answer(
                    await _format_congress_msg_help(
                        server_id,
                        header="❌ Использование: /msg [алиас] [текст]",
                    )
                )
            else:
                await message.answer(
                    await _format_aliases_message(
                        server_id,
                        header="❌ Использование: /msg [алиас] [текст]",
                    )
                )
            return

        parts = raw.split(maxsplit=1)
        alias = parts[0]
        msg_text = parts[1].strip() if len(parts) > 1 else ""

        if not msg_text and not attachments:
            header = f"❌ Укажите текст: /msg {alias} [текст]"
            reply = (
                await _format_congress_msg_help(server_id, header=header)
                if msg_mode == "congress"
                else await _format_aliases_message(server_id, header=header)
            )
            await message.answer(reply)
            return

        target, err = await _resolve_msg_target(server_id, alias, msg_mode=msg_mode)
        if err:
            await message.answer(err)
            return
        if not target:
            return

        send_body = await messaging.build_alert_message(
            peer_id=target.peer_id,
            text=msg_text,
            sender_vk_id=message.from_id,
            server_id=server_id,
        )
        preview_body = await messaging.build_alert_preview(
            peer_id=target.peer_id,
            text=msg_text,
            sender_vk_id=message.from_id,
            server_id=server_id,
        )
        token = create_pending_msg(
            user_id=message.from_id,
            server_id=server_id,
            alias=target.alias or alias,
            target_peer_id=target.peer_id,
            target_title=target.title,
            text=msg_text,
            send_body=send_body,
            preview_body=preview_body,
            attachments=attachments,
        )
        preview_text = _format_msg_preview(
            alias=target.alias or alias,
            target_title=target.title,
            text=msg_text or "📷",
            preview_body=preview_body,
            attachments=attachments,
        )
        await message.answer(
            preview_text,
            keyboard=create_msg_confirm_keyboard(token),
            disable_mentions=1,
        )

    @bot.on.raw_event(GroupEventType.MESSAGE_EVENT, MessageEvent, blocking=False)
    async def msg_confirm_callback(event: MessageEvent) -> None:
        payload = event.payload
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                return
        if not isinstance(payload, dict):
            return

        cmd = payload.get("cmd")
        if cmd not in ("msg_confirm", "msg_cancel"):
            return

        allowed, _server_id, _mode = await _can_use_msg(event.user_id, event.peer_id)
        if not allowed:
            await event.show_snackbar("⛔ Недостаточно прав.")
            return

        token = payload.get("token")
        if not token:
            await event.show_snackbar("❌ Запрос устарел.")
            return

        if cmd == "msg_cancel":
            pop_pending_msg(token, event.user_id)
            await event.send_message("❌ Отправка оповещения отменена.")
            await event.send_empty_answer()
            return

        pending = pop_pending_msg(token, event.user_id)
        if not pending:
            await event.show_snackbar("⏰ Время подтверждения истекло.")
            return

        await event.send_message("📤 Отправляю оповещение...")
        await event.send_empty_answer()
        await _send_pool_alert(
            sender_id=event.user_id,
            server_id=pending.server_id,
            source_peer_id=event.peer_id,
            alias=pending.alias,
            target_peer_id=pending.target_peer_id,
            target_title=pending.target_title,
            text=pending.text,
            send_body=pending.send_body,
            attachments=pending.attachments,
        )
