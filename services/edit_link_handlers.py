"""Команды /editmydiscord и /editmyforum — регистрируются из main.py."""

from __future__ import annotations

import logging

from vkbottle.bot import Bot, Message
from vkbottle.dispatch.rules.base import FuncRule

from database.repository.user_repo import UserRepository
from middlewares.access import requires_public
from middlewares.action_logger import ActionLogger
from services.command_utils import matches_cmd, strip_cmd
from services.forum_account import FORUM_MEMBER_URL_HINT, forum_member_url, normalize_forum_account
from services.panel_client import get_discord_link, set_discord_link

logger = logging.getLogger(__name__)

_DISCORD_CLEAR = frozenset({"off", "0", "нет", "remove", "clear", "снять", "удалить"})
_FORUM_CLEAR = frozenset({"off", "0", "нет", "remove", "clear", "снять", "удалить"})


def register_edit_link_commands(bot: Bot, action_logger: ActionLogger) -> None:
    @bot.on.message(FuncRule(lambda m: matches_cmd(m.text or "", "editmydiscord")))
    @requires_public
    async def editmydiscord_cmd(
        message: Message,
        server_id: int = 0,
        access_level: int = 0,
    ) -> None:
        user_id = message.from_id or 0
        logger.info("editmydiscord peer=%s vk=%s text=%r", message.peer_id, user_id, message.text)
        try:
            raw = strip_cmd(message.text or "", "editmydiscord").strip()

            if not raw:
                current = await get_discord_link(user_id)
                lines = [
                    "Привязка Discord для входа на сайт",
                    "",
                ]
                if current:
                    lines.append(f"Сейчас указан: {current}")
                else:
                    lines.append("Сейчас Discord ID не указан.")
                lines.extend(
                    [
                        "",
                        "Команды:",
                        "/editmydiscord 12345678901234567 — указать свой ID",
                        "/editmydiscord off — снять привязку",
                        "",
                        "Где взять ID: Discord → Настройки → Расширенные → "
                        "режим разработчика → ПКМ по профилю → «Скопировать ID пользователя».",
                    ]
                )
                await message.answer("\n".join(lines))
                return

            if raw.lower() in _DISCORD_CLEAR:
                ok, err = await set_discord_link(user_id, None)
                if ok:
                    await message.answer(
                        "✅ Discord ID снят. Вход через Discord на сайте недоступен, "
                        "пока не укажете новый."
                    )
                else:
                    await message.answer(f"❌ {err}")
                return

            ok, err = await set_discord_link(user_id, raw)
            if ok:
                await message.answer(
                    f"✅ Discord ID сохранён: {raw}\n"
                    "Теперь можно войти на сайт через «Войти через Discord»."
                )
                await action_logger.log_user(
                    "editmydiscord",
                    user_id,
                    raw,
                    "Привязка Discord ID",
                )
            else:
                await message.answer(f"❌ {err}")
        except Exception:
            logger.exception("editmydiscord vk=%s", user_id)
            await message.answer("❌ Не удалось обработать команду. Попробуйте позже.")

    @bot.on.message(FuncRule(lambda m: matches_cmd(m.text or "", "editmyforum")))
    @requires_public
    async def editmyforum_cmd(
        message: Message,
        server_id: int = 0,
        access_level: int = 0,
    ) -> None:
        user_id = message.from_id or 0
        logger.info("editmyforum peer=%s vk=%s text=%r", message.peer_id, user_id, message.text)
        try:
            raw = strip_cmd(message.text or "", "editmyforum").strip()

            if not raw:
                current = await UserRepository.get_forum_member_id(user_id)
                lines = [
                    "Привязка профиля форума",
                    "",
                ]
                if current:
                    lines.append(f"Сейчас указан: {forum_member_url(current)}")
                else:
                    lines.append("Сейчас профиль форума не указан.")
                lines.extend(
                    [
                        "",
                        "Команды:",
                        f"/editmyforum {FORUM_MEMBER_URL_HINT} — указать ссылку",
                        "/editmyforum off — снять привязку",
                        "",
                        "Ссылка: откройте свой профиль на forum.arizona-rp.com и скопируйте URL.",
                    ]
                )
                await message.answer("\n".join(lines))
                return

            if raw.lower() in _FORUM_CLEAR:
                await UserRepository.set_forum_member_id(user_id, None)
                await message.answer("✅ Профиль форума снят.")
                await action_logger.log_user(
                    "editmyforum",
                    user_id,
                    "clear",
                    "Снята привязка форума",
                )
                return

            try:
                member_id = normalize_forum_account(raw)
            except ValueError as exc:
                await message.answer(f"❌ {exc}")
                return

            await UserRepository.ensure_user(vk_id=user_id, added_by=user_id)
            await UserRepository.set_forum_member_id(user_id, member_id)
            url = forum_member_url(member_id)
            await message.answer(f"✅ Профиль форума сохранён:\n{url}")
            await action_logger.log_user(
                "editmyforum",
                user_id,
                member_id,
                "Привязка форума",
            )
        except Exception:
            logger.exception("editmyforum vk=%s", user_id)
            await message.answer("❌ Не удалось обработать команду. Попробуйте позже.")

    logger.info("Команды editmydiscord / editmyforum зарегистрированы")
