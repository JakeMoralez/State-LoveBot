"""Назначение следящего через /reg — вызов internal API панели."""

from __future__ import annotations

import logging
import re
import shlex

from vkbottle import API
from vkbottle.bot import Bot, Message

from database.models.user import AccessLevel
from database.repository.user_repo import UserRepository
from database.spheres import (
    CENTRAL_APPARATUS,
    DEFENSE,
    GOV_STRUCTURES,
    HEALTH,
    JUSTICE,
)
from middlewares.access import AccessChecker, requires_level
from middlewares.action_logger import ActionLogger
from services.command_utils import dual, dual_args, strip_cmd
from services.display_name import DisplayNameService
from services.forum_account import (
    FORUM_MEMBER_ID_RE,
    FORUM_MEMBER_URL_HINT,
    FORUM_MEMBER_URL_RE,
)
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
_NICK_RE = re.compile(
    r"^[A-Za-zА-Яа-яЁё][A-Za-zА-Яа-яЁё0-9]*_[A-Za-zА-Яа-яЁё][A-Za-zА-Яа-яЁё0-9]*$"
)

_REG_SPHERE_KEYS = frozenset(
    {
        CENTRAL_APPARATUS,
        JUSTICE,
        DEFENSE,
        HEALTH,
        GOV_STRUCTURES,
    }
)


def _grant_range(access_level: int, *, is_dev: bool) -> tuple[int, int]:
    """(min, max) уровень, который может выдать актор."""
    if is_dev:
        return AccessLevel.PGS, AccessLevel.GA
    max_grant = min(AccessLevel.ZGA, max(AccessLevel.PGS, access_level - 1))
    return AccessLevel.PGS, max_grant


def _reg_usage(*, access_level: int = 0, is_dev: bool = False) -> str:
    lo, hi = _grant_range(access_level, is_dev=is_dev)
    if hi < lo:
        level_hint = "нет доступных уровней (нужен выше)"
    else:
        level_hint = f"{lo}–{hi}"
    return (
        "❌ /reg [@user] [никнейм] [уровень] [сферы] [forum] [discord]\n"
        "\n"
        f"Пример:\n"
        f"/reg @user Name_Surname 2 ца {FORUM_MEMBER_URL_HINT} 987654321012345678\n"
        "\n"
        "👉 Никнейм: Name_Surname (без тега — тег уровня подставится сам)\n"
        f"👉 Уровень: {level_hint}\n"
        "👉 Сферы: ца, мю, мо, мз, гос\n"
        f"👉 Форум: ссылка вида {FORUM_MEMBER_URL_HINT}\n"
        "👉 Discord ID: 17–20 цифр "
        "(Discord → настройки → «Режим разработчика» → ПКМ по профилю → «Скопировать ID»)"
    )


def _looks_like_forum(token: str) -> bool:
    t = (token or "").strip()
    return bool(FORUM_MEMBER_URL_RE.match(t) or FORUM_MEMBER_ID_RE.match(t))


def _looks_like_discord(token: str) -> bool:
    return bool(_DISCORD_ID_RE.match((token or "").strip()))


def _parse_reg_args(
    args: str,
    *,
    access_level: int = 0,
    is_dev: bool = False,
) -> tuple[int, list[str], str, str, str] | str:
    """(level, spheres, nickname, forum, discord) или текст ошибки.

    Порядок: никнейм · уровень · сферы · forum · discord
    """
    usage = _reg_usage(access_level=access_level, is_dev=is_dev)
    try:
        parts = shlex.split(args, posix=True)
    except ValueError as exc:
        return str(exc)

    if len(parts) < 5:
        return usage

    nickname = strip_nickname_tags(parts[0]).strip()
    if not nickname:
        return "❌ Укажите никнейм в формате Name_Surname."
    if not _NICK_RE.match(nickname):
        return (
            "❌ Никнейм в формате Name_Surname\n"
            "(латиница или кириллица, одно подчёркивание, без тега и пробелов)."
        )

    try:
        level = int(parts[1])
    except ValueError:
        return "❌ Уровень — число (см. доступный диапазон в /reg)."

    lo, hi = _grant_range(access_level, is_dev=is_dev)
    if level < lo or level > hi:
        return f"❌ Уровень должен быть в диапазоне {lo}–{hi}."

    try:
        spheres = parse_sphere_tokens(parts[2])
    except ValueError as exc:
        return f"❌ {exc}"

    bad = [s for s in spheres if s not in _REG_SPHERE_KEYS]
    if bad:
        return "❌ Для /reg доступны сферы: ца, мю, мо, мз, гос."

    forum = parts[3].strip()
    discord = parts[4].strip()
    if len(parts) > 5:
        return usage
    if not _looks_like_forum(forum):
        return f"❌ Форум: ссылка вида {FORUM_MEMBER_URL_HINT}"
    if not _looks_like_discord(discord):
        return (
            "❌ Discord ID: 17–20 цифр.\n"
            "Включите режим разработчика в Discord → ПКМ по профилю → «Скопировать ID»."
        )

    return level, spheres, nickname, forum, discord


def register_staff_reg(bot: Bot, api: API, action_logger: ActionLogger) -> None:
    names = DisplayNameService(api)

    @bot.on.message(text=dual("reg"))
    @requires_level(AccessLevel.ZGS, command="reg")
    async def reg_usage(
        message: Message,
        server_id: int = 0,
        access_level: int = 0,
    ) -> None:
        del server_id
        is_dev = await UserRepository.is_developer(message.from_id or 0)
        await message.answer(_reg_usage(access_level=access_level, is_dev=is_dev))

    @bot.on.message(text=dual_args("reg", "<args>"))
    @requires_level(AccessLevel.ZGS, command="reg")
    async def reg_staff(
        message: Message,
        args: str,
        server_id: int = 0,
        access_level: int = 0,
    ) -> None:
        del args
        is_dev = await UserRepository.is_developer(message.from_id or 0)
        usage = _reg_usage(access_level=access_level, is_dev=is_dev)

        if not panel_api_configured():
            await message.answer(
                "❌ Панель не настроена (PANEL_INTERNAL_URL / SLED_BOT_SECRET).\n"
                "Назначьте следящего через сайт: /assign?type=staff"
            )
            return

        raw = strip_cmd(message.text or "", "reg").strip()
        if not raw:
            await message.answer(usage)
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
                await message.answer(usage)
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

        parsed = _parse_reg_args(
            remainder.strip(),
            access_level=access_level,
            is_dev=is_dev,
        )
        if isinstance(parsed, str):
            await message.answer(parsed)
            return

        level, spheres, nickname, forum, discord = parsed

        granter_level = AccessLevel.DEVELOPER if is_dev else access_level
        if level >= granter_level and not is_dev:
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
