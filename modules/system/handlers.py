"""Системные команды: /me, /getid."""

from __future__ import annotations

from vkbottle import API
from vkbottle.bot import Bot, Message

from database.repository.forum_role_repo import ForumRoleRepository
from database.repository.user_repo import UserRepository
from middlewares.access import AccessChecker
from services.command_utils import dual
from services.display_name import DisplayNameService


def register_system(bot: Bot, api: API) -> None:
    @bot.on.message(text=dual("getid"))
    async def show_chat_id(message: Message) -> None:
        peer_id = message.peer_id
        if peer_id >= 2_000_000_000:
            chat_id = peer_id - 2_000_000_000
            await message.answer(
                f"📌 ID этой беседы:\n"
                f"• peer_id: {peer_id}\n"
                f"• chat_id: {chat_id}"
            )
        else:
            await message.answer(
                f"📌 Это личные сообщения\n"
                f"• peer_id: {peer_id}"
            )

    @bot.on.message(text=dual("me"))
    async def show_me(message: Message) -> None:
        user_id = message.from_id or 0
        server_id = await AccessChecker.resolve_server_id(message.peer_id)
        level = await UserRepository.get_access_level(user_id, server_id)
        level_name = AccessChecker.level_name(level) if level else "нет доступа"

        names = DisplayNameService(api)
        link = await names.mention_user(user_id)

        lines = [
            "📝 Основая информация о пользователе ⬇",
            f"👤 Ник пользователя: {link}",
            f"👥 Уровень доступа: {level_name}",
        ]
        if await ForumRoleRepository.is_judge(user_id):
            lines.append("⚖️ Судебный доступ: есть")

        await message.answer("\n".join(lines), disable_mentions=0)
