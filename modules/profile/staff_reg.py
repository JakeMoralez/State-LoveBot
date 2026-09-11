"""Назначение следящего через /reg — вызов internal API панели."""

from __future__ import annotations

import logging
import re
import shlex

from vkbottle import API
from vkbottle.bot import Bot, Message

from database.models.user import AccessLevel
from database.repository.user_repo import UserRepository
from middlewares.access import AccessChecker, requires_level
from middlewares.action_logger import ActionLogger
from services.command_utils import dual, dual_args, strip_cmd
from services.display_name import DisplayNameService
from services.forum_account import FORUM_MEMBER_ID_RE, FORUM_MEMBER_URL_RE
from services.panel_client import assign_staff_via_panel, panel_api_configured
from services.panel_db import read_staff_spheres
from services.staff_nickname import strip_nickname_tags
from services.staff_spheres import (
    constrain_spheres_for_actor,
    format_spheres_display,
    parse_sphere_tokens,
    validate_spheres,
)
from services.vk_resolver import VKResolver

logger = logging.getLogger(__name__)

_DISCORD_ID_RE = re.compile(r"^\d{17,20}$")

_REG_USAGE = (
    "❌ /reg [@user] [уровень] [сферы] [forum] [discord]\n"
    "Опционально имя: /reg @user 2 ца Имя 655354 987654321012345678\n"
    "Сферы: ца, мю, мо, мз, гос, нелег, сервер\n"
    "Имя не обязательно — возьмём из ника/VK. Тег уровня подставится сам."
)


def _looks_like_forum(token: str) -> bool:
    t = (token or "").strip()
    return bool(FORUM_MEMBER_URL_RE.match(t) or FORUM_MEMBER_ID_RE.match(t))


def _looks_like_discord(token: str) -> bool:
    return bool(_DISCORD_ID_RE.match((token or "").strip()))


def _parse_reg_args(args: str) -> tuple[int, list[str], str, str, str] | str:
    """(level, spheres, nickname, forum, discord) или текст ошибки.

    Имя опционально: /reg … 2 ца forum discord  или  … 2 ца Имя forum discord
    """
    try:
        parts = shlex.split(args, posix=True)
    except ValueError as exc:
        return str(exc)

    if len(parts) < 4:
        return _REG_USAGE

    try:
        level = int(parts[0])
    except ValueError:
        return "❌ Уровень — число от 1."

    if level < AccessLevel.PGS:
        return "❌ Уровень должен быть не ниже 1 (ПС)."

    try:
        spheres = parse_sphere_tokens(parts[1])
    except ValueError as exc:
        return f"❌ {exc}"

    forum = parts[-2].strip()
    discord = parts[-1].strip()
    if not _looks_like_forum(forum):
        return "❌ Укажите ссылку или ID профиля на forum.arizona-rp.com"
    if not _looks_like_discord(discord):
        return "❌ Укажите Discord ID (17–20 цифр)"

    nickname = " ".join(parts[2:-2]).strip()
    return level, spheres, nickname, forum, discord


async def _resolve_reg_nickname(
    api: API,
    *,
    vk_id: int,
    server_id: int,
    provided: str,
) -> str:
    clean = strip_nickname_tags(provided).strip()
    if clean:
        return clean

    existing = await UserRepository.get_nickname(vk_id, server_id)
    clean = strip_nickname_tags(existing or "").strip()
    if clean:
        return clean

    try:
        users = await api.users.get(user_ids=[vk_id])
        if users:
            u = users[0]
            first = (getattr(u, "first_name", None) or "").strip()
            last = (getattr(u, "last_name", None) or "").strip()
            full = f"{first} {last}".strip()
            if full:
                return full.replace(" ", "_")
    except Exception as exc:
        logger.debug("reg nickname vk resolve failed vk=%s: %s", vk_id, exc)

    return f"id{vk_id}"


def register_staff_reg(bot: Bot, api: API, action_logger: ActionLogger) -> None:
    names = DisplayNameService(api)

    @bot.on.message(text=dual("reg"))
    @requires_level(AccessLevel.ZGS, command="reg")
    async def reg_usage(
        message: Message,
        server_id: int = 0,
        access_level: int = 0,
    ) -> None:
        del server_id, access_level
        await message.answer(_REG_USAGE)

    @bot.on.message(text=dual_args("reg", "<args>"))
    @requires_level(AccessLevel.ZGS, command="reg")
    async def reg_staff(
        message: Message,
        args: str,
        server_id: int = 0,
        access_level: int = 0,
    ) -> None:
        del args
        if not panel_api_configured():
            await message.answer(
                "❌ Панель не настроена (PANEL_INTERNAL_URL / SLED_BOT_SECRET).\n"
                "Назначьте следящего через сайт: /assign?type=staff"
            )
            return

        raw = strip_cmd(message.text or "", "reg").strip()
        if not raw:
            await message.answer(_REG_USAGE)
            return

        reply_id = (
            message.reply_message.from_id
            if message.reply_message and message.reply_message.from_id > 0
            else None
        )

        if reply_id:
            remainder = raw
            resolved, hint = await VKResolver(api, server_id).resolve_from_message_with_hint(
                "",
                reply_from_id=reply_id,
                server_id=server_id,
            )
        else:
            target_raw, _, remainder = raw.partition(" ")
            if not remainder.strip():
                await message.answer(_REG_USAGE)
                return
            resolved, hint = await VKResolver(api, server_id).resolve_from_message_with_hint(
                target_raw,
                reply_from_id=None,
                server_id=server_id,
            )
        if hint:
            await message.answer(hint, disable_mentions=1)
            return
        if not resolved:
            await message.answer(
                "❌ Пользователь не найден.\n"
                "Укажите VK-ссылку, id или ответьте на сообщение."
            )
            return

        if resolved.vk_id == message.from_id:
            await message.answer("❌ Нельзя назначить себя.")
            return

        parsed = _parse_reg_args(remainder.strip())
        if isinstance(parsed, str):
            await message.answer(parsed)
            return

        level, spheres, nickname_raw, forum, discord = parsed
        nickname = await _resolve_reg_nickname(
            api,
            vk_id=resolved.vk_id,
            server_id=server_id,
            provided=nickname_raw,
        )

        is_dev = await UserRepository.is_developer(message.from_id or 0)
        granter_level = AccessLevel.DEVELOPER if is_dev else access_level
        max_grant = AccessLevel.GA if is_dev else AccessLevel.ZGA

        if level > max_grant:
            await message.answer(f"❌ Доступны уровни 1–{max_grant}.")
            return
        if level >= granter_level:
            await message.answer("❌ Нельзя выдать уровень равный или выше своего.")
            return

        try:
            spheres = validate_spheres(spheres, access_level=level)
            if not is_dev:
                actor_spheres = await read_staff_spheres(
                    message.from_id or 0, server_id
                )
                spheres = constrain_spheres_for_actor(
                    granter_level,
                    actor_spheres,
                    [],
                    spheres,
                    level,
                )
        except ValueError as exc:
            await message.answer(f"❌ {exc}")
            return

        old_level = await UserRepository.get_access_level(resolved.vk_id, server_id)
        if old_level > 0:
            await message.answer(
                "❌ У пользователя уже есть доступ следящего.\n"
                "Измените уровень через /setlevel или профиль на сайте."
            )
            return

        ok, result = await assign_staff_via_panel(
            actor_vk_id=message.from_id or 0,
            server_id=server_id,
            vk_id=resolved.vk_id,
            nickname=nickname,
            access_level=level,
            spheres=spheres,
            forum_account=forum,
            discord_id=discord,
        )
        if not ok:
            await message.answer(f"❌ {result}")
            return

        bot_nick = result.get("nickname") if isinstance(result, dict) else None
        bot_nick = bot_nick or nickname
        granter = await names.link_user(message.from_id or 0, server_id)
        target = await names.link_user(resolved.vk_id, server_id)
        level_name = AccessChecker.level_name(level)
        sphere_text = format_spheres_display(spheres)

        await message.answer(
            f"✅ {granter} назначил {target} следящим.\n"
            f"🏷 {bot_nick}\n"
            f"📊 {level_name} ({level}) · {sphere_text}",
            disable_mentions=1,
        )
        await action_logger.log_user(
            "reg_staff",
            message.from_id,
            f"id{resolved.vk_id} → ур. {level}, {sphere_text}",
            "Назначен",
            source_peer_id=message.peer_id,
        )
