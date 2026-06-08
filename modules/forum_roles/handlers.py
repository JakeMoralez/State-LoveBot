"""Судебные роли: /addcourt, /regcourt, /court, /rcourt, /removecourt."""

from __future__ import annotations

import logging
from datetime import datetime

from vkbottle import API
from vkbottle.bot import Bot, Message

from database.models.role_chat import ForumRoleKey
from database.models.user import AccessLevel
from database.repository.forum_role_repo import ForumRoleRepository
from database.repository.user_repo import UserRepository
from middlewares.access import requires_developer, requires_level
from middlewares.action_logger import ActionLogger
from middlewares.forum_access import requires_court_manager
from services.command_utils import dual, dual_args
from services.display_name import DisplayNameService
from services.vk_resolver import VKResolver

logger = logging.getLogger(__name__)


def _parse_target_and_note(args: str) -> tuple[str, str]:
    parts = args.strip().split(maxsplit=1)
    target = parts[0] if parts else ""
    note = parts[1] if len(parts) > 1 else ""
    return target, note


def _judge_since(user) -> str:
    dt = user.last_used or user.added_at
    if not dt:
        return "—"
    if isinstance(dt, datetime):
        return dt.strftime("%d.%m.%Y")
    return str(dt)


async def _format_judge_list(users: list, api: API) -> str:
    if not users:
        return "📭 Судей нет."
    names = DisplayNameService(api)
    lines = [f"⚖️ Судьи ({len(users)}):"]
    for user in users:
        link = await names.mention_user(user.vk_id)
        lines.append(f"• {link} — Судья с {_judge_since(user)}")
    return "\n".join(lines)


def register_forum_roles(bot: Bot, api: API, action_logger: ActionLogger) -> None:
    resolver = VKResolver(api)

    @bot.on.message(text=dual_args("addcourt"))
    @requires_level(AccessLevel.SUPERVISOR)
    async def add_court(
        message: Message,
        args: str | None = None,
        server_id: int = 0,
        access_level: int = 0,
    ) -> None:
        if not args and not (
            message.reply_message and message.reply_message.from_id > 0
        ):
            await message.answer(
                "❌ /addcourt [@user] [заметка]\n"
                "Или ответом на сообщение."
            )
            return

        reply_id = (
            message.reply_message.from_id
            if message.reply_message and message.reply_message.from_id > 0
            else None
        )
        target_raw, note = _parse_target_and_note(args or "")
        resolved = await resolver.resolve_from_message(target_raw, reply_from_id=reply_id)
        if not resolved:
            await message.answer("❌ Пользователь не найден.")
            return

        await ForumRoleRepository.set_role(
            vk_id=resolved.vk_id,
            username=resolved.username,
            added_by=message.from_id,
            note=note,
            is_judge=True,
        )
        names = DisplayNameService(api)
        link = await names.mention_user(resolved.vk_id)
        await message.answer(
            f"⚖️ {link} назначен судьёй.",
            disable_mentions=0,
        )
        target_label = resolved.display_name or resolved.username or f"id{resolved.vk_id}"
        await action_logger.log_user(
            "add_court",
            message.from_id,
            f"{target_label} (id{resolved.vk_id})" + (f", {note}" if note else ""),
            "Назначен судьёй",
            source_peer_id=message.peer_id,
        )

    @bot.on.message(text=dual_args("deluser", "<target>"))
    @requires_developer
    async def del_user(
        message: Message,
        target: str | None = None,
        server_id: int = 0,
        access_level: int = 0,
    ) -> None:
        reply_id = (
            message.reply_message.from_id
            if message.reply_message and message.reply_message.from_id > 0
            else None
        )
        resolved = await resolver.resolve_from_message(target or "", reply_from_id=reply_id)
        if resolved:
            ok = await ForumRoleRepository.remove_user(resolved.vk_id)
        else:
            ok = await ForumRoleRepository.remove_user_by_username((target or "").strip())
        await message.answer("✅ Удалён." if ok else "❌ Не найден.")
        target_label = (
            f"id{resolved.vk_id}" if resolved else (target or "").strip()
        )
        await action_logger.log_user(
            "deluser",
            message.from_id,
            target_label,
            "Удалён" if ok else "Не найден",
            source_peer_id=message.peer_id,
        )

    @bot.on.message(text=dual("rcourt"))
    @requires_level(AccessLevel.SUPERVISOR)
    async def rcourt_self(message: Message, server_id: int = 0, access_level: int = 0) -> None:
        ok = await ForumRoleRepository.clear_judge_role(message.from_id)
        await message.answer("✅ Доступ судьи снят." if ok else "❌ Вы не судья.")
        if ok:
            await action_logger.log_user(
                "remove_judge",
                message.from_id,
                f"id{message.from_id}",
                "Снят (rcourt)",
                source_peer_id=message.peer_id,
            )

    @bot.on.message(text=dual("removecourt"))
    @requires_level(AccessLevel.SUPERVISOR)
    async def removecourt_self(message: Message, server_id: int = 0, access_level: int = 0) -> None:
        user = await UserRepository.get_by_vk_id(message.from_id)
        if not user or not user.is_judge:
            await message.answer("❌ Вы не зарегистрированы как судья.")
            return
        since = _judge_since(user)
        ok = await ForumRoleRepository.clear_judge_role(message.from_id)
        if ok:
            link = await DisplayNameService(api).mention_user(message.from_id)
            await message.answer(
                f"✅ С вас снят статус судьи.\n"
                f"• {link} — Судья с {since}\n"
                f"Доступ к судебным функциям отозван.",
                disable_mentions=0,
            )
        else:
            await message.answer("❌ Не удалось снять доступ.")
        if ok:
            await action_logger.log_user(
                "remove_judge",
                message.from_id,
                f"id{message.from_id}",
                "Снят (removecourt)",
                source_peer_id=message.peer_id,
            )

    @bot.on.message(text=dual("regcourt"))
    @requires_court_manager
    async def reg_court_chat(message: Message, server_id: int = 0) -> None:
        if message.peer_id < 2_000_000_000:
            await message.answer("❌ Только в беседах.")
            return
        await ForumRoleRepository.save_role_chat(
            ForumRoleKey.JUDGE,
            message.peer_id,
            message.from_id or 0,
            server_id,
        )
        await message.answer(
            "✅ Беседа судей привязана.\n"
            "При выходе из неё роль судьи снимается автоматически."
        )
        await action_logger.log_user(
            "regcourt",
            message.from_id,
            f"peer {message.peer_id}",
            "Беседа судей привязана",
            source_peer_id=message.peer_id,
        )

    @bot.on.message(text=dual("court"))
    @requires_court_manager
    async def list_court(message: Message, server_id: int = 0) -> None:
        users = await ForumRoleRepository.list_by_role(ForumRoleKey.JUDGE)
        await message.answer(
            await _format_judge_list(users, api),
            disable_mentions=0,
        )
