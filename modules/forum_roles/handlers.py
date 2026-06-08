"""Судебные роли: /addcourt, /court."""

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
from middlewares.ca_access import requires_ca_scope
from middlewares.action_logger import ActionLogger
from middlewares.forum_access import requires_court_manager
from services.command_utils import dual, dual_args
from services.display_name import DisplayNameService
from services.vk_resolver import VKResolver

logger = logging.getLogger(__name__)


def _parse_target_and_note(args: str) -> tuple[str, str]:
    parts = args.strip().split(maxsplit=1)
    target = VKResolver.extract_reference(parts[0]) if parts else ""
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
        link = await names.link_user(user.vk_id)
        lines.append(f"• {link} — Судья с {_judge_since(user)}")
    return "\n".join(lines)


def register_forum_roles(bot: Bot, api: API, action_logger: ActionLogger) -> None:
    resolver = VKResolver(api)

    @bot.on.message(text=dual_args("addcourt"))
    @requires_level(AccessLevel.SUPERVISOR)
    @requires_ca_scope
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
        resolved, hint = await resolver.resolve_from_message_with_hint(
            target_raw, reply_from_id=reply_id
        )
        if hint:
            await message.answer(hint, disable_mentions=1)
            return
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
        link = await names.link_user(resolved.vk_id)
        await message.answer(
            f"⚖️ {link} назначен судьёй.",
            disable_mentions=1,
        )
        target_label = resolved.display_name or resolved.username or f"id{resolved.vk_id}"
        await action_logger.log_user(
            "add_court",
            message.from_id,
            f"{target_label} (id{resolved.vk_id})" + (f", {note}" if note else ""),
            "Назначен судьёй",
            source_peer_id=message.peer_id,
        )

    @bot.on.message(text=dual_args("deluser"))
    @requires_developer
    async def del_user(
        message: Message,
        args: str | None = None,
        server_id: int = 0,
        access_level: int = 0,
    ) -> None:
        if not args and not (
            message.reply_message and message.reply_message.from_id > 0
        ):
            await message.answer(
                "❌ /deluser (/du) [@user|vk.com|vk.ru]\n"
                "Или ответом на сообщение."
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
        if resolved:
            ok = await ForumRoleRepository.remove_user(resolved.vk_id)
        else:
            ok = await ForumRoleRepository.remove_user_by_username(
                (args or "").strip()
            )
        await message.answer("✅ Удалён." if ok else "❌ Не найден.")
        target_label = (
            f"id{resolved.vk_id}" if resolved else (args or "").strip()
        )
        await action_logger.log_user(
            "deluser",
            message.from_id,
            target_label,
            "Удалён" if ok else "Не найден",
            source_peer_id=message.peer_id,
        )

    @bot.on.message(text=dual("court"))
    @requires_court_manager
    async def list_court(message: Message, server_id: int = 0) -> None:
        users = await ForumRoleRepository.list_by_role(ForumRoleKey.JUDGE)
        await message.answer(
            await _format_judge_list(users, api),
            disable_mentions=1,
        )
