"""Админ-команды беседы: find, online, mute, stitle, reg, настройки."""

from __future__ import annotations

import json
import logging

from vkbottle import API, GroupEventType
from vkbottle.bot import Bot, Message, MessageEvent
from vkbottle.dispatch.rules.base import FuncRule

from database.models.chat_settings import GuardMode
from database.models.user import AccessLevel
from database.repository.chat_repo import ChatRepository
from database.repository.chat_settings_repo import ChatSettingsRepository
from middlewares.access import requires_level, requires_public
from middlewares.action_logger import ActionLogger
from services.blacklist_sheets import check_blacklist
from services.chat_admin import ChatAdminService
from services.chat_settings_keyboard import create_open_edit_keyboard, create_value_keyboard
from services.chat_settings_pending import clear as clear_chat_settings_session
from services.chat_settings_pending import get as get_chat_settings_session
from services.chat_settings_pending import is_callback_owner
from services.chat_settings_pending import register_owner
from services.chat_settings_pending import start_pick_setting
from services.chat_settings_ui import (
    CHAT_SETTINGS,
    CHAT_SETTINGS_BY_NUMBER,
    apply_setting,
    format_setting_updated,
    format_settings_edit_panel,
    format_settings_overview,
)
from services.command_utils import dual, dual_with_args, strip_cmd
from services.display_name import DisplayNameService
from services.staff_hierarchy import can_act_on_target
from services.vk_resolver import VKResolver

logger = logging.getLogger(__name__)


def _require_chat(message: Message) -> bool:
    return message.peer_id >= 2_000_000_000


def register_chat_admin(bot: Bot, api: API, action_logger: ActionLogger) -> None:
    admin = ChatAdminService(api)
    resolver = VKResolver(api)
    names = DisplayNameService(api)

    async def _resolve_target(message: Message, args: str, server_id: int) -> int | None:
        reply_id = (
            message.reply_message.from_id
            if message.reply_message and message.reply_message.from_id > 0
            else None
        )
        resolved = await VKResolver(api, server_id).resolve_from_message(
            args or "",
            reply_from_id=reply_id,
            server_id=server_id,
        )
        return resolved.vk_id if resolved else None

    @bot.on.message(text=dual("find"))
    @requires_public
    async def find_usage(message: Message, server_id: int = 0, access_level: int = 0) -> None:
        await message.answer(
            "❌ /find [ник / @user / ссылка]\n"
            "Пример: /find rp123"
        )

    @bot.on.message(text=dual_with_args("find", "<query>"))
    @requires_public
    async def find_user(
        message: Message,
        query: str,
        server_id: int = 0,
        access_level: int = 0,
    ) -> None:
        text = await admin.format_find_results(query, server_id)
        await message.answer(text, disable_mentions=1)

    async def _resolve_checkbl_query(
        message: Message,
        query: str,
        server_id: int,
    ) -> str:
        reply_id = (
            message.reply_message.from_id
            if message.reply_message and message.reply_message.from_id > 0
            else None
        )
        resolved, _hint = await resolver.resolve_from_message_with_hint(
            query or "",
            reply_from_id=reply_id,
            server_id=server_id,
        )
        if resolved:
            for candidate in (resolved.display_name, resolved.username):
                if candidate and candidate.strip():
                    return candidate.strip()
        return (query or "").strip()

    @bot.on.message(text=dual("checkbl"))
    @requires_public
    async def checkbl_usage(
        message: Message,
        server_id: int = 0,
        access_level: int = 0,
    ) -> None:
        await message.answer(
            "❌ /checkbl [ник / UUID / @user]\n"
            "Пример: /checkbl Daniel_Bradberry"
        )

    @bot.on.message(text=dual_with_args("checkbl", "<query>"))
    @requires_public
    async def checkbl_lookup(
        message: Message,
        query: str,
        server_id: int = 0,
        access_level: int = 0,
    ) -> None:
        lookup = await _resolve_checkbl_query(message, query, server_id)
        if not lookup:
            await message.answer("❌ Укажите ник, UUID или пользователя.")
            return
        text = await check_blacklist(lookup)
        await message.answer(text, disable_mentions=1)

    @bot.on.message(text=dual("online"))
    @requires_public
    async def online_members(
        message: Message,
        server_id: int = 0,
        access_level: int = 0,
    ) -> None:
        if not _require_chat(message):
            await message.answer("❌ Команда только в беседах.")
            return
        text = await admin.format_online_list(message.peer_id)
        await message.answer(text, disable_mentions=1)

    @bot.on.message(text=dual("regdate"))
    @requires_public
    async def regdate_cmd(message: Message, server_id: int = 0, access_level: int = 0) -> None:
        if message.reply_message and message.reply_message.from_id > 0:
            target_id = message.reply_message.from_id
        elif message.from_id and message.from_id > 0:
            target_id = message.from_id
        else:
            await message.answer(
                "❌ /regdate [@user]\n"
                "Или ответом на сообщение."
            )
            return
        text = await admin.format_registration_date(target_id)
        await message.answer(text, disable_mentions=1)

    @bot.on.message(text=dual_with_args("regdate", "<target>"))
    @requires_public
    async def regdate_for_target(
        message: Message,
        target: str,
        server_id: int = 0,
        access_level: int = 0,
    ) -> None:
        target_id = await _resolve_target(message, target, server_id)
        if not target_id:
            await message.answer("❌ Пользователь не найден.")
            return
        text = await admin.format_registration_date(target_id)
        await message.answer(text, disable_mentions=1)

    @bot.on.message(text=dual("mute"))
    @requires_level(AccessLevel.SUPERVISOR)
    async def mute_usage(
        message: Message,
        server_id: int = 0,
        access_level: int = 0,
    ) -> None:
        await message.answer(
            "❌ /mute [@user] [время] [причина]\n"
            "Время: 30m, 1h, 2d\n"
            "Или ответом: /mute 30m спам"
        )

    @bot.on.message(text=dual_with_args("mute", "<args>"))
    @requires_level(AccessLevel.SUPERVISOR)
    async def mute_user(
        message: Message,
        args: str,
        server_id: int = 0,
        access_level: int = 0,
    ) -> None:
        if not _require_chat(message):
            await message.answer("❌ Команда только в беседах.")
            return

        reason: str | None = None
        if message.reply_message and message.reply_message.from_id > 0:
            target_id = message.reply_message.from_id
            reply_parts = args.strip().split(maxsplit=1)
            if not reply_parts:
                await message.answer("❌ Ответом: /mute [время] [причина]")
                return
            seconds = admin.parse_duration(reply_parts[0])
            if not seconds:
                await message.answer("❌ Укажите время: 30m, 1h, 2d")
                return
            reason = reply_parts[1].strip() if len(reply_parts) > 1 else None
        else:
            target_raw, seconds, reason = admin.parse_mute_args(args)
            if not target_raw or not seconds:
                await message.answer("❌ /mute [@user] [время] [причина]")
                return
            target_id = await _resolve_target(message, target_raw, server_id)
            if not target_id:
                await message.answer("❌ Пользователь не найден.")
                return

        if not seconds or seconds < 1:
            await message.answer("❌ Укажите время: 30m, 1h, 2d.")
            return

        actor_id = message.from_id or 0
        if target_id == actor_id:
            await message.answer("❌ Нельзя выдать мут самому себе.")
            return
        allowed, hier_err = await can_act_on_target(
            actor_id,
            access_level,
            target_id,
            server_id,
            on_equal_or_higher=(
                "❌ Нельзя выдать мут пользователю своего уровня или выше."
            ),
            on_developer="❌ Нельзя выдать мут разработчику.",
        )
        if not allowed:
            await message.answer(hier_err or "❌ Недостаточно прав.")
            return

        ok, err = await admin.mute_member(
            message.peer_id, target_id, seconds=seconds
        )
        if ok:
            link = await names.link_user(target_id, server_id)
            lines = [
                f"🔇 {link} — мут на {admin.format_duration(seconds)}.",
            ]
            if reason:
                lines.append(f"📝 Причина: {reason}")
            await message.answer("\n".join(lines), disable_mentions=1)
            await action_logger.log_user(
                "mute",
                message.from_id,
                f"id{target_id}, {seconds}s"
                + (f", {reason}" if reason else ""),
                "Выдан",
                source_peer_id=message.peer_id,
            )
        else:
            await message.answer(f"❌ Не удалось выдать мут.\n{err}")

    @bot.on.message(text=dual("unmute"))
    @requires_level(AccessLevel.SUPERVISOR)
    async def unmute_usage(
        message: Message,
        server_id: int = 0,
        access_level: int = 0,
    ) -> None:
        await message.answer("❌ /unmute [@user] — или ответом на сообщение.")

    @bot.on.message(text=dual_with_args("unmute", "<target>"))
    @requires_level(AccessLevel.SUPERVISOR)
    async def unmute_user(
        message: Message,
        target: str,
        server_id: int = 0,
        access_level: int = 0,
    ) -> None:
        if not _require_chat(message):
            await message.answer("❌ Команда только в беседах.")
            return
        target_id = await _resolve_target(message, target, server_id)
        if not target_id:
            await message.answer("❌ Пользователь не найден.")
            return

        actor_id = message.from_id or 0
        if target_id == actor_id:
            await message.answer("❌ Нельзя снять мут с самого себя этой командой.")
            return
        allowed, hier_err = await can_act_on_target(
            actor_id,
            access_level,
            target_id,
            server_id,
            on_equal_or_higher=(
                "❌ Нельзя снять мут с пользователя своего уровня или выше."
            ),
            on_developer="❌ Нельзя снять мут с разработчика.",
        )
        if not allowed:
            await message.answer(hier_err or "❌ Недостаточно прав.")
            return

        ok, err = await admin.unmute_member(message.peer_id, target_id)
        if ok:
            link = await names.link_user(target_id, server_id)
            await message.answer(f"🔊 С {link} снят мут.", disable_mentions=1)
            await action_logger.log_user(
                "unmute",
                message.from_id,
                f"id{target_id}",
                "Снят",
                source_peer_id=message.peer_id,
            )
        else:
            await message.answer(f"❌ Не удалось снять мут.\n{err}")

    @bot.on.message(text=dual("stitle"))
    @requires_level(AccessLevel.ZGS)
    async def stitle_usage(
        message: Message,
        server_id: int = 0,
        access_level: int = 0,
    ) -> None:
        await message.answer("❌ /stitle [новое название беседы]")

    @bot.on.message(text=dual_with_args("stitle", "<title>"))
    @requires_level(AccessLevel.ZGS)
    async def set_title(
        message: Message,
        title: str,
        server_id: int = 0,
        access_level: int = 0,
    ) -> None:
        if not _require_chat(message):
            await message.answer("❌ Команда только в беседах.")
            return

        ok, result = await admin.set_chat_title(message.peer_id, title)
        if ok:
            chat = await ChatRepository.get_by_peer_id(message.peer_id)
            if chat:
                chat.title = result
                await chat.save()
            await message.answer(f"✅ Название беседы: «{result}»")
            await action_logger.log_user(
                "stitle",
                message.from_id,
                result[:80],
                "Изменено",
                source_peer_id=message.peer_id,
            )
        else:
            await message.answer(f"❌ {result}")

    @bot.on.message(text=dual("chatsettings"))
    @requires_level(AccessLevel.ZGS)
    async def show_settings(
        message: Message,
        server_id: int = 0,
        access_level: int = 0,
    ) -> None:
        if not _require_chat(message):
            await message.answer("❌ Команда только в беседах.")
            return
        owner_id = message.from_id or 0
        register_owner(message.peer_id, owner_id)
        text = await format_settings_overview(api, message.peer_id)
        await message.answer(
            text,
            keyboard=create_open_edit_keyboard(owner_id),
            disable_mentions=1,
        )

    def _chat_settings_pick_rule(message: Message) -> bool:
        if not _require_chat(message):
            return False
        user_id = message.from_id or 0
        session = get_chat_settings_session(message.peer_id, user_id)
        if not session or session.phase != "pick_setting":
            return False
        return (message.text or "").strip() in {"1", "2", "3"}

    @bot.on.message(FuncRule(_chat_settings_pick_rule), blocking=True)
    @requires_level(AccessLevel.ZGS)
    async def chat_settings_pick_number(
        message: Message,
        server_id: int = 0,
        access_level: int = 0,
    ) -> None:
        number = int((message.text or "").strip())
        setting = CHAT_SETTINGS_BY_NUMBER.get(number)
        if not setting:
            await message.answer("❌ Нет такого пункта. Укажите 1, 2 или 3.")
            return
        owner_id = message.from_id or 0
        await message.answer(
            f"⚙ {setting.title}\nВыберите значение:",
            keyboard=create_value_keyboard(setting.key, owner_id),
            disable_mentions=1,
        )

    @bot.on.raw_event(GroupEventType.MESSAGE_EVENT, MessageEvent, blocking=False)
    async def chat_settings_callback(event: MessageEvent) -> None:
        payload = event.payload
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                return
        if not isinstance(payload, dict) or payload.get("cmd") != "chat_cfg":
            return

        if event.peer_id < 2_000_000_000:
            await event.show_snackbar("❌ Только в беседах.")
            return

        from middlewares.access import AccessChecker

        server_id = await AccessChecker.resolve_server_id(event.peer_id, event.user_id)
        if await AccessChecker.get_level(event.user_id, server_id) < AccessLevel.ZGS:
            await event.show_snackbar("⛔ Недостаточно прав.")
            return

        action = payload.get("action")
        peer_id = event.peer_id
        owner_id = payload.get("owner")

        if action in ("edit", "set") and not is_callback_owner(event.user_id, owner_id):
            await event.show_snackbar("⛔ Только автор команды.")
            await event.send_empty_answer()
            return

        if action == "edit":
            start_pick_setting(peer_id, event.user_id)
            panel = await format_settings_edit_panel(api, peer_id)
            await event.send_message(panel, disable_mentions=1)
            await event.send_empty_answer()
            return

        if action == "set":
            field = payload.get("key")
            value = payload.get("value")
            setting = CHAT_SETTINGS.get(str(field or ""))
            if not setting or not value:
                await event.show_snackbar("❌ Некорректный запрос.")
                return
            try:
                await apply_setting(
                    peer_id,
                    setting.field,
                    str(value),
                    updated_by=event.user_id,
                )
            except ValueError as exc:
                await event.show_snackbar(f"❌ {exc}")
                return
            clear_chat_settings_session(peer_id, event.user_id)
            await event.send_message(
                format_setting_updated(setting.field, str(value)),
                disable_mentions=1,
            )
            await action_logger.log_user(
                "chatsettings",
                event.user_id,
                f"{setting.slug}={value}",
                "Изменено",
                source_peer_id=peer_id,
            )
            await event.send_empty_answer()
            return

    def _register_rejoin(cmd: str, field: str) -> None:
        @bot.on.message(text=dual(cmd))
        @requires_level(AccessLevel.ZGS)
        async def _usage(
            message: Message,
            server_id: int = 0,
            access_level: int = 0,
            *,
            _cmd: str = cmd,
        ) -> None:
            await message.answer(f"❌ /{_cmd} on|off|ask")

        @bot.on.message(text=dual_with_args(cmd, "<mode>"))
        @requires_level(AccessLevel.ZGS)
        async def _set(
            message: Message,
            mode: str,
            server_id: int = 0,
            access_level: int = 0,
            *,
            _cmd: str = cmd,
            _field: str = field,
        ) -> None:
            if not _require_chat(message):
                await message.answer("❌ Команда только в беседах.")
                return
            normalized = ChatSettingsRepository.normalize_mode(mode)
            if not normalized:
                await message.answer("❌ Режим: on, off или ask")
                return
            await ChatSettingsRepository.set_mode(
                message.peer_id,
                _field,
                normalized,
                updated_by=message.from_id,
                allow_ask=_field == "kick_on_leave",
            )
            if _field == "kick_on_leave":
                settings = await ChatSettingsRepository.get(message.peer_id)
                settings.rejoin_kick = normalized
                await settings.save()
            label = (
                ChatSettingsRepository.leave_mode_label(normalized)
                if _field == "kick_on_leave"
                else ChatSettingsRepository.mode_label(normalized)
            )
            await message.answer(f"✅ /{_cmd} → {label}")

    _register_rejoin("rejoinkick", "kick_on_leave")
