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
from middlewares.congress_access import requires_setnick
from middlewares.action_logger import ActionLogger
from services.command_utils import dual, dual_with_args, matches_cmd, strip_cmd
from services.display_name import DisplayNameService
from services.nickname import NicknameValidator
from services.staff_display import format_staff_list
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


_VK_REF = r"(?:https?://)?(?:m\.)?(?:vk\.com|vk\.ru)/(?:id\d+|[\w.]+)"
_SETNICK_LEAD = re.compile(
    rf"^(?:\[id(\d+)\|[^\]]+\]|@(\S+)|({_VK_REF}))(?:\s+)(.+)$",
    re.DOTALL | re.IGNORECASE,
)


_SETNICK_FORMAT_ERR = (
    "❌ Неверный формат.\n"
    "Сначала пинг: @user, [id|имя] или vk.ru/…, затем ник.\n"
    "Или ответом на сообщение."
)

_NICK_TARGET_ERR = (
    "❌ Неверный формат.\n"
    "Укажите @user, [id|имя], vk.ru/… или ответьте на сообщение."
)

_VK_REF_ONLY = re.compile(
    rf"^(?:\[id(\d+)\|[^\]]+\]|@(\S+)|({_VK_REF}))$",
    re.IGNORECASE,
)


async def _parse_setnick(message: Message, api: API) -> tuple[int | None, str | None, str | None]:
    """(target_id, nickname, error_message)."""
    args = strip_cmd(message.text or "", "setnick")
    if not args:
        return None, None, _SETNICK_FORMAT_ERR

    resolver = VKResolver(api)

    if message.reply_message and message.reply_message.from_id > 0:
        nick = args.strip()
        if not nick:
            return None, None, "❌ Укажите никнейм."
        return message.reply_message.from_id, nick, None

    lead = _SETNICK_LEAD.match(args)
    if not lead:
        return None, None, _SETNICK_FORMAT_ERR

    vk_id_raw, screen, url_ref, nickname = (
        lead.group(1),
        lead.group(2),
        lead.group(3),
        lead.group(4).strip(),
    )
    if not nickname:
        return None, None, "❌ Укажите никнейм."

    if vk_id_raw:
        return int(vk_id_raw), nickname, None

    if screen:
        resolved = await resolver.resolve(f"@{screen}")
        if resolved:
            return resolved.vk_id, nickname, None
        return None, None, _SETNICK_FORMAT_ERR

    if url_ref:
        resolved = await resolver.resolve(url_ref)
        if resolved:
            return resolved.vk_id, nickname, None
        return None, None, _SETNICK_FORMAT_ERR

    return None, None, _SETNICK_FORMAT_ERR


async def _parse_nick_target(message: Message, api: API) -> tuple[int | None, str | None]:
    """(target_id, error_message) — для /rnick."""
    args = strip_cmd(message.text or "", "rnick")
    resolver = VKResolver(api)

    if message.reply_message and message.reply_message.from_id > 0:
        return message.reply_message.from_id, None

    if not args:
        return None, _NICK_TARGET_ERR

    lead = _VK_REF_ONLY.match(args.strip())
    if not lead:
        return None, _NICK_TARGET_ERR

    vk_id_raw, screen, url_ref = lead.group(1), lead.group(2), lead.group(3)
    if vk_id_raw:
        return int(vk_id_raw), None
    if screen:
        resolved = await resolver.resolve(f"@{screen}")
        if resolved:
            return resolved.vk_id, None
        return None, _NICK_TARGET_ERR
    if url_ref:
        resolved = await resolver.resolve(url_ref)
        if resolved:
            return resolved.vk_id, None
        return None, _NICK_TARGET_ERR

    return None, _NICK_TARGET_ERR


async def format_who_card(vk_id: int, api: API) -> str:
    emoji = random.choice(_WHO_EMOJIS)
    link = await DisplayNameService(api).link_user(vk_id)
    return f"{emoji} {link}"


def register_profile(bot: Bot, api: API, action_logger: ActionLogger) -> None:
    names = DisplayNameService(api)

    @bot.on.message(FuncRule(lambda m: matches_cmd(m.text or "", "setnick")))
    @requires_setnick
    async def setnick(
        message: Message,
        server_id: int = 0,
        access_level: int = 0,
    ) -> None:
        target_id, nickname, err = await _parse_setnick(message, api)
        if err:
            await message.answer(err)
            return
        if not nickname or target_id is None:
            await message.answer("❌ Укажите никнейм.")
            return

        ok, val_err = NicknameValidator.validate(nickname)
        if not ok:
            await message.answer(f"❌ {val_err}")
            return

        if await UserRepository.has_nickname(target_id):
            await message.answer("❌ Никнейм уже установлен. Сначала /rnick.")
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
        actor = await names.format_setnick_actor(message.from_id or 0)
        target_link = DisplayNameService.nick_link(target_id, nickname)
        await message.answer(
            f"{actor} поставил никнейм '{nickname}' {target_link}.",
            disable_mentions=1,
        )
        await action_logger.log_user(
            "setnick",
            message.from_id,
            f"id{target_id} → {nickname}",
            "Установлен",
            source_peer_id=message.peer_id,
        )

    @bot.on.message(FuncRule(lambda m: matches_cmd(m.text or "", "rnick")))
    @requires_setnick
    async def rnick(
        message: Message,
        server_id: int = 0,
        access_level: int = 0,
    ) -> None:
        target_id, err = await _parse_nick_target(message, api)
        if err:
            await message.answer(err)
            return
        if target_id is None:
            await message.answer(_NICK_TARGET_ERR)
            return

        if not await UserRepository.has_nickname(target_id):
            link = await names.link_user(target_id)
            await message.answer(
                f"❌ У {link} нет никнейма.",
                disable_mentions=1,
            )
            return

        user = await UserRepository.get_by_vk_id(target_id)
        old_nick = user.nickname if user else ""
        await UserRepository.clear_nickname(target_id)
        actor = await names.format_setnick_actor(message.from_id or 0)
        target_link = await names.link_user(target_id)
        await message.answer(
            f"{actor} снял никнейм '{old_nick}' у {target_link}.",
            disable_mentions=1,
        )
        await action_logger.log_user(
            "rnick",
            message.from_id,
            f"id{target_id} ← {old_nick}",
            "Снят",
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
        await message.answer(text, disable_mentions=1)

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
        await message.answer(card, disable_mentions=1)

    @bot.on.message(text=dual("setlevel"))
    @requires_level(AccessLevel.ZGS)
    async def setlevel_usage(
        message: Message,
        server_id: int = 0,
        access_level: int = 0,
    ) -> None:
        max_lvl = 9 if await UserRepository.is_developer(message.from_id or 0) else 8
        await message.answer(
            f"❌ Использование: /setlevel [vk.ru|ID|@user|ник] [0-{max_lvl}]"
        )

    @bot.on.message(text=dual_with_args("setlevel", "<target> <level>"))
    @requires_level(AccessLevel.ZGS)
    async def set_level(
        message: Message,
        target: str,
        level: str,
        server_id: int = 0,
        access_level: int = 0,
    ) -> None:
        is_dev = await UserRepository.is_developer(message.from_id)
        max_grant = 9 if is_dev else 8

        try:
            new_level = int(level)
        except ValueError:
            await message.answer(f"❌ Уровень — число от 0 до {max_grant}.")
            return
        if new_level < 0 or new_level > max_grant:
            await message.answer(f"❌ Доступны уровни 0–{max_grant}.")
            return

        granter_level = access_level
        if is_dev:
            granter_level = AccessLevel.DEVELOPER
        if new_level > granter_level:
            await message.answer("❌ Нельзя выдать уровень выше своего.")
            return

        resolver = VKResolver(api)
        resolved, hint = await resolver.resolve_with_hint(target.strip())
        if hint:
            await message.answer(hint, disable_mentions=1)
            return
        if not resolved:
            await message.answer(
                "❌ Пользователь не найден.\n"
                "Укажите VK-ссылку, id или ник из /setnick."
            )
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
        if new_level == 0:
            result_text = "Доступ снят (ур. 0)."
            log_detail = "Снят"
        else:
            name = AccessChecker.level_name(new_level)
            result_text = f"Выдан уровень {name}."
            log_detail = "Выдан"
        await message.answer(
            f"✅ {await format_who_card(resolved.vk_id, api)}\n{result_text}",
            disable_mentions=1,
        )
        await action_logger.log_user(
            "setlevel",
            message.from_id,
            f"id{resolved.vk_id} → ур. {new_level}",
            log_detail,
            source_peer_id=message.peer_id,
        )
