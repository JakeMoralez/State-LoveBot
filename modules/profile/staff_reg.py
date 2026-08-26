"""Назначение следящего через /reg — вызов internal API панели."""

from __future__ import annotations

import logging
import shlex

from vkbottle import API
from vkbottle.bot import Bot, Message

from database.models.user import AccessLevel
from database.repository.user_repo import UserRepository
from middlewares.access import AccessChecker, requires_level
from middlewares.action_logger import ActionLogger
from services.command_utils import dual, dual_args, strip_cmd
from services.display_name import DisplayNameService
from services.panel_client import assign_staff_via_panel, panel_api_configured
from services.panel_db import read_staff_spheres
from services.staff_spheres import (
    constrain_spheres_for_actor,
    format_spheres_display,
    parse_sphere_tokens,
    validate_spheres,
)
from services.vk_resolver import VKResolver

logger = logging.getLogger(__name__)

_REG_USAGE = (
    "❌ /reg [@user] [уровень] [сферы] [имя] [forum] [discord]\n"
    "Сферы: ца, мю, мо, мз, гос, нелег, сервер\n"
    "Пример: /reg @user 2 ца Иван 655354 987654321012345678\n"
    "Имя в кавычках, если несколько слов"
)


def _parse_reg_args(args: str) -> tuple[int, list[str], str, str, str] | str:
    """(level, spheres, nickname, forum, discord) или текст ошибки."""
    try:
        parts = shlex.split(args, posix=True)
    except ValueError as exc:
        return str(exc)

    if len(parts) < 5:
        return _REG_USAGE

    try:
        level = int(parts[0])
    except ValueError:
        return "❌ Уровень — число от 1."

    if level < AccessLevel.PGS:
        return "❌ Уровень должен быть не ниже 1 (ПГС)."

    try:
        spheres = parse_sphere_tokens(parts[1])
    except ValueError as exc:
        return f"❌ {exc}"

    forum = parts[-2].strip()
    discord = parts[-1].strip()
    nickname = " ".join(parts[2:-2]).strip()

    if not nickname:
        return "❌ Укажите имя (без тега — тег подставится автоматически)."
    if not forum:
        return "❌ Укажите ссылку или ID профиля на forum.arizona-rp.com"
    if not discord:
        return "❌ Укажите Discord ID"

    return level, spheres, nickname, forum, discord


def register_staff_reg(bot: Bot, api: API, action_logger: ActionLogger) -> None:
    names = DisplayNameService(api)

    @bot.on.message(text=dual("reg"))
    @requires_level(AccessLevel.ZGS)
    async def reg_usage(
        message: Message,
        server_id: int = 0,
        access_level: int = 0,
    ) -> None:
        await message.answer(_REG_USAGE)

    @bot.on.message(text=dual_args("reg", "<args>"))
    @requires_level(AccessLevel.ZGS)
    async def reg_staff(
        message: Message,
        args: str,
        server_id: int = 0,
        access_level: int = 0,
    ) -> None:
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

        level, spheres, nickname, forum, discord = parsed

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

        bot_nick = result.get("nickname") or nickname
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
