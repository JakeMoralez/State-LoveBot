"""Профили: /setnick, /who, /setlevel."""

from __future__ import annotations

import logging
import random
import re

from vkbottle import API
from vkbottle.bot import Bot, Message
from vkbottle.dispatch.rules.base import FuncRule

from database.models.user import AccessLevel
from database.repository.user_repo import UserRepository
from middlewares.access import AccessChecker, requires_level, requires_public
from middlewares.action_logger import ActionLogger
from services.command_utils import dual, matches_cmd, strip_cmd
from services.display_name import DisplayNameService
from services.nickname import NicknameValidator
from services.vk_resolver import VKResolver

logger = logging.getLogger(__name__)

_WHO_EMOJIS = (
    "😀", "😃", "😄", "😁", "😆", "😅", "🤣", "😂", "🙂", "🙃", "😉", "😊",
    "😇", "🥰", "😍", "🤩", "😘", "😗", "😚", "😙", "🥲", "😋", "😛", "😜",
    "🤪", "😝", "🤑", "🤗", "🤭", "🤫", "🤔", "🤐", "🤨", "😐", "😑", "😶",
    "😏", "😒", "🙄", "😬", "🤥", "😌", "😔", "😪", "🤤", "😴", "😷", "🤒",
    "🤕", "🤢", "🤮", "🤧", "🥵", "🥶", "🥴", "😵", "🤯", "🤠", "🥳", "🥸",
    "😎", "🤓", "🧐", "😕", "😟", "🙁", "☹️", "😮", "😯", "😲", "😳", "🥺",
    "😦", "😧", "😨", "😰", "😥", "😢", "😭", "😱", "😖", "😣", "😞", "😓",
    "😩", "😫", "🥱", "😤", "😡", "😠", "🤬", "😈", "👿", "🫠", "🫡", "🫢",
    "🫣", "🫤", "🫥", "🫨",
)


_SETNICK_LEAD = re.compile(
    r"^(?:\[id(\d+)\|[^\]]+\]|@(\S+))(?:\s+)(.+)$",
    re.DOTALL,
)


async def _parse_setnick(message: Message, api: API) -> tuple[int | None, str | None, str | None]:
    """(target_id, nickname, error_message)."""
    args = strip_cmd(message.text or "", "setnick")
    if not args:
        return None, None, (
            "❌ Использование: /setnick [@user] [никнейм]\n"
            "Пример: /setnick @user @user [Speaker] Имя\n"
            "Или ответом на сообщение: /setnick [никнейм]"
        )

    resolver = VKResolver(api)

    if message.reply_message and message.reply_message.from_id > 0:
        return message.reply_message.from_id, args.strip(), None

    lead = _SETNICK_LEAD.match(args)
    if lead:
        vk_id_raw, screen, nickname = lead.group(1), lead.group(2), lead.group(3).strip()
        if vk_id_raw:
            return int(vk_id_raw), nickname, None
        resolved = await resolver.resolve(f"@{screen}")
        if resolved:
            return resolved.vk_id, nickname, None

    parts = args.split(maxsplit=1)
    if len(parts) == 2:
        resolved = await resolver.resolve(parts[0])
        if resolved:
            return resolved.vk_id, parts[1].strip(), None

    return message.from_id, args.strip(), None


async def format_who_card(vk_id: int, api: API) -> str:
    emoji = random.choice(_WHO_EMOJIS)
    link = await DisplayNameService(api).mention_user(vk_id)
    return f"{emoji} {link}"


async def format_staff_list(server_id: int, api: API) -> str:
    rows = await UserRepository.list_server_access(server_id)
    if not rows:
        return "📭 Пользователей с доступом нет."

    names = DisplayNameService(api)
    lines = [f"🔐 Доступы ({len(rows)}):"]
    for user, level in rows:
        link = await names.mention_user(user.vk_id)
        title = AccessChecker.level_name(level)
        lines.append(f"• {link} — {title} ({level})")
    return "\n".join(lines)


def register_profile(bot: Bot, api: API, action_logger: ActionLogger) -> None:
    @bot.on.message(FuncRule(lambda m: matches_cmd(m.text or "", "setnick")))
    @requires_level(AccessLevel.PGS, require_registered=True)
    async def setnick(
        message: Message,
        server_id: int = 0,
        access_level: int = 0,
    ) -> None:
        target_id, nickname, err = await _parse_setnick(message, api)
        if err:
            await message.answer(err)
            return
        if not nickname:
            await message.answer("❌ Укажите никнейм.")
            return

        ok, val_err = NicknameValidator.validate(nickname)
        if not ok:
            await message.answer(f"❌ {val_err}")
            return

        if target_id != message.from_id:
            resolver = VKResolver(api)
            resolved = await resolver.resolve(str(target_id))
            await UserRepository.ensure_user(
                vk_id=target_id,
                username=resolved.username if resolved else None,
                added_by=message.from_id,
            )

        await UserRepository.set_nickname(target_id, nickname)
        link = DisplayNameService.nick_link(target_id, nickname)
        await message.answer(f"✅ Никнейм установлен: {link}", disable_mentions=0)
        await action_logger.log_user(
            "setnick",
            message.from_id,
            f"id{target_id} → {nickname}",
            "Установлен",
            source_peer_id=message.peer_id,
        )

    @bot.on.message(text=dual("staff") + dual("admins"))
    @requires_level(AccessLevel.PGS, require_registered=True)
    async def staff(
        message: Message,
        server_id: int = 0,
        access_level: int = 0,
    ) -> None:
        text = await format_staff_list(server_id, api)
        await message.answer(text, disable_mentions=0)

    @bot.on.message(text=["/who", "!who", "кто"])
    @requires_public
    async def who(
        message: Message,
        server_id: int = 0,
        access_level: int = 0,
    ) -> None:
        target_id: int | None = None
        if message.reply_message and message.reply_message.from_id > 0:
            target_id = message.reply_message.from_id
        elif message.from_id:
            target_id = message.from_id

        if not target_id:
            await message.answer("ℹ️ Ответьте на сообщение пользователя.")
            return

        card = await format_who_card(target_id, api)
        await message.answer(card, disable_mentions=0)

    @bot.on.message(text=["/setlevel", "!setlevel"])
    @requires_level(AccessLevel.ZGS)
    async def setlevel_usage(
        message: Message,
        server_id: int = 0,
        access_level: int = 0,
    ) -> None:
        await message.answer("❌ Использование: /setlevel [ссылка/ID] [1-8]")

    @bot.on.message(text=["/setlevel <target> <level>", "!setlevel <target> <level>"])
    @requires_level(AccessLevel.ZGS)
    async def set_level(
        message: Message,
        target: str,
        level: str,
        server_id: int = 0,
        access_level: int = 0,
    ) -> None:
        try:
            new_level = int(level)
        except ValueError:
            await message.answer("❌ Уровень — число от 1 до 8.")
            return
        if new_level < 1 or new_level > 8:
            await message.answer("❌ Доступны уровни 1–8.")
            return

        granter_level = access_level
        if await UserRepository.is_developer(message.from_id):
            granter_level = AccessLevel.DEVELOPER
        if new_level > granter_level:
            await message.answer("❌ Нельзя выдать уровень выше своего.")
            return

        resolver = VKResolver(api)
        resolved = await resolver.resolve(target.strip())
        if not resolved:
            await message.answer("❌ Пользователь не найден.")
            return

        await UserRepository.ensure_user(
            vk_id=resolved.vk_id,
            username=resolved.username,
            added_by=message.from_id,
        )
        await UserRepository.set_access_level(
            vk_id=resolved.vk_id,
            server_id=server_id,
            level=new_level,
            granted_by=message.from_id,
        )
        name = AccessChecker.level_name(new_level)
        await message.answer(
            f"✅ {await format_who_card(resolved.vk_id, api)}\n"
            f"Выдан уровень {name}.",
            disable_mentions=0,
        )
        await action_logger.log_user(
            "setlevel",
            message.from_id,
            f"id{resolved.vk_id} → ур. {new_level} ({name})",
            "Выдан",
            source_peer_id=message.peer_id,
        )
