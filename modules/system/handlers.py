"""Системные команды: /me, /getid, /meserver, /setserver."""

from __future__ import annotations

from vkbottle import API
from vkbottle.bot import Bot, Message

from database.repository.congress_repo import CongressRepository
from database.repository.forum_role_repo import ForumRoleRepository
from database.repository.server_repo import ServerRepository
from database.repository.user_repo import UserRepository
from middlewares.access import AccessChecker, requires_developer
from services.command_utils import dual, dual_args, strip_cmd
from services.dev_server_context import (
    clear_dev_server_override,
    get_dev_server_override,
    set_dev_server_override,
)
from services.display_name import DisplayNameService
from services.server_display import format_judge_forum_hint, format_server_label


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
        server_id = await AccessChecker.resolve_server_id(message.peer_id, user_id)
        level = await UserRepository.get_access_level(user_id, server_id)
        level_name = AccessChecker.level_name(level) if level else "нет доступа"

        names = DisplayNameService(api, server_id)
        link = await names.link_user(user_id, server_id)
        server = await ServerRepository.get_by_id(server_id)
        server_label = format_server_label(server, server_id)

        lines = [
            "📝 Основая информация о пользователе ⬇",
            f"🌐 Сервер: {server_label}",
            f"👤 Ник пользователя: {link}",
            f"👥 Уровень доступа: {level_name}",
        ]
        if await ForumRoleRepository.is_judge_effective(user_id, server_id):
            lines.append("⚖️ Судебный доступ: есть")
        if await CongressRepository.is_officer(user_id, server_id):
            access = await UserRepository.get_server_access(user_id, server_id)
            if access and access.is_congress_speaker:
                lines.append("🎙 Спикер конгресса")
            elif access and access.is_congress_vice:
                lines.append("🎖 Вице-спикер конгресса")

        await message.answer("\n".join(lines), disable_mentions=1)

    @bot.on.message(text=dual_args("meserver", "<text>"))
    @requires_developer
    async def switch_dev_server(
        message: Message,
        server_id: int = 0,
        access_level: int = 0,
    ) -> None:
        user_id = message.from_id or 0
        arg = strip_cmd(message.text or "", "meserver").strip().lower()

        if not arg:
            override = get_dev_server_override(user_id)
            effective = await AccessChecker.resolve_server_id(message.peer_id, user_id)
            server = await ServerRepository.get_by_id(effective)
            label = format_server_label(server, effective)
            lines = [f"📌 Активный сервер: {label}"]
            if override is not None:
                lines.append("↪ Переключён через /meserver")
            else:
                lines.append("↪ Из беседы или сервер по умолчанию")
            lines.append("\n/meserver <номер> — переключить\n/meserver off — сбросить")
            await message.answer("\n".join(lines))
            return

        if arg in ("off", "reset", "0", "none"):
            clear_dev_server_override(user_id)
            effective = await AccessChecker.resolve_server_id(message.peer_id, user_id)
            await message.answer(
                f"✅ Сброшено. Активный server_id: {effective}"
            )
            return

        if not arg.isdigit() or int(arg) <= 0:
            await message.answer("❌ Укажите номер сервера, например: /meserver 30")
            return

        target_id = int(arg)
        server = await ServerRepository.get_or_create_by_id(target_id)
        set_dev_server_override(user_id, target_id)
        await message.answer(
            f"✅ Активный сервер: {format_server_label(server, target_id)}"
        )

    def _format_server_settings(server_id: int, server) -> str:
        label = format_server_label(server, server_id)
        lines = [f"⚙️ Настройки сервера {label}", ""]
        if server:
            lines.append(f"• Имя: {server.name}")
            lines.append(f"• Тег: {server.tag or '—'}")
            if server.judge_forum_id:
                lines.append(
                    f"• Раздел исков: {format_judge_forum_hint(server.judge_forum_id)}"
                )
            else:
                lines.append("• Раздел исков: не задан")
        else:
            lines.append("• Запись не найдена — задайте параметры ниже")
        lines.extend(
            [
                "",
                "/setserver tag <имя> — тег для /me (Love)",
                "/setserver forum <id> — раздел судебных исков",
                "/setserver name <полное имя>",
                "/setserver forum off — сбросить раздел",
            ]
        )
        return "\n".join(lines)

    @bot.on.message(text=dual_args("setserver", "<text>"))
    @requires_developer
    async def set_server_settings(
        message: Message,
        server_id: int = 0,
        access_level: int = 0,
    ) -> None:
        arg = strip_cmd(message.text or "", "setserver").strip()
        server = await ServerRepository.get_by_id(server_id)

        if not arg:
            await message.answer(_format_server_settings(server_id, server))
            return

        lower = arg.lower()
        if lower.startswith("tag "):
            value = arg[4:].strip()
            if not value:
                await message.answer("❌ /setserver tag <имя>")
                return
            server = await ServerRepository.update_settings(server_id, tag=value)
            await message.answer(
                f"✅ Тег: {server.tag}\n{format_server_label(server, server_id)}"
            )
            return

        if lower.startswith("name "):
            value = arg[5:].strip()
            if not value:
                await message.answer("❌ /setserver name <полное имя>")
                return
            server = await ServerRepository.update_settings(server_id, name=value)
            await message.answer(
                f"✅ Имя: {server.name}\n{format_server_label(server, server_id)}"
            )
            return

        if lower in ("forum off", "judge off", "иски off"):
            server = await ServerRepository.update_settings(
                server_id,
                clear_judge_forum=True,
            )
            await message.answer(
                f"✅ Раздел исков сброшен.\n{_format_server_settings(server_id, server)}"
            )
            return

        if lower.startswith("forum ") or lower.startswith("judge ") or lower.startswith(
            "иски "
        ):
            prefix = "forum " if lower.startswith("forum ") else (
                "judge " if lower.startswith("judge ") else "иски "
            )
            raw_id = arg[len(prefix) :].strip()
            if not raw_id.isdigit() or int(raw_id) <= 0:
                await message.answer("❌ /setserver forum <id> — число из URL forums/3423/")
                return
            forum_id = int(raw_id)
            server = await ServerRepository.update_settings(
                server_id,
                judge_forum_id=forum_id,
            )
            await message.answer(
                f"✅ Раздел исков: {format_judge_forum_hint(forum_id)}\n"
                f"{format_server_label(server, server_id)}"
            )
            return

        await message.answer(
            "❌ Неизвестный параметр.\n\n" + _format_server_settings(server_id, server)
        )
