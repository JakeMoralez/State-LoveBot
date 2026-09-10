"""Админ-команды беседы: find, online, mute, stitle, reg, настройки."""

from __future__ import annotations

import json
import logging
import re

from vkbottle import API, GroupEventType
from vkbottle.bot import Bot, Message, MessageEvent
from vkbottle.dispatch.rules.base import FuncRule

from database.models.chat_settings import GuardMode
from database.models.user import AccessLevel
from database.repository.chat_repo import ChatRepository
from database.repository.chat_settings_repo import ChatSettingsRepository
from middlewares.access import requires_level, requires_public
from middlewares.action_logger import ActionLogger
from services import responses as resp
from services.blacklist_sheets import CHECKBL_BATCH_MAX, check_blacklist_many
from services.chat_admin import ChatAdminService
from services.chat_settings_keyboard import (
    create_kind_keyboard,
    create_open_edit_keyboard,
    create_sphere_keyboard,
    create_value_keyboard,
)
from services.chat_settings_pending import clear as clear_chat_settings_session
from services.chat_settings_pending import get as get_chat_settings_session
from services.chat_settings_pending import is_callback_owner
from services.chat_settings_pending import register_owner
from services.chat_settings_pending import start_pick_kind
from services.chat_settings_pending import start_pick_setting
from services.chat_settings_pending import start_pick_sphere
from services.chat_settings_ui import (
    CHAT_SETTINGS,
    CHAT_SETTINGS_BY_NUMBER,
    KIND_PICK_ITEMS,
    apply_setting,
    format_kind_pick_text,
    format_setting_updated,
    format_settings_edit_panel,
    format_settings_overview,
    format_sphere_pick_text,
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
    @requires_level(0, command="find", require_registered=False)
    async def find_usage(message: Message, server_id: int = 0, access_level: int = 0) -> None:
        await message.answer(
            resp.error("/find [ник / @user / ссылка]\n"
            "Пример: /find rp123")
        )

    @bot.on.message(text=dual_with_args("find", "<query>"))
    @requires_level(0, command="find", require_registered=False)
    async def find_user(
        message: Message,
        query: str,
        server_id: int = 0,
        access_level: int = 0,
    ) -> None:
        text = await admin.format_find_results(query, server_id)
        await message.answer(text, disable_mentions=1)

    async def _resolve_checkbl_token(
        token: str,
        server_id: int,
    ) -> str:
        query = (token or "").strip()
        if not query:
            return ""

        q_lower = query.lower()
        is_vk_ref = (
            query.startswith("@")
            or "vk.com" in q_lower
            or "vk.ru" in q_lower
            or re.match(r"\[id\d+\|", query, re.IGNORECASE)
        )
        if is_vk_ref:
            resolved, _hint = await resolver.resolve_from_message_with_hint(
                query,
                server_id=server_id,
            )
            if resolved:
                for candidate in (resolved.display_name, resolved.username):
                    if candidate and candidate.strip():
                        return candidate.strip()
            return query

        return query

    async def _resolve_checkbl_queries(
        message: Message,
        raw: str,
        server_id: int,
    ) -> list[str]:
        raw = (raw or "").strip()
        reply_id = (
            message.reply_message.from_id
            if message.reply_message and message.reply_message.from_id > 0
            else None
        )
        if not raw:
            if not reply_id:
                return []
            resolved, _hint = await resolver.resolve_from_message_with_hint(
                "",
                reply_from_id=reply_id,
                server_id=server_id,
            )
            if resolved:
                for candidate in (resolved.display_name, resolved.username):
                    if candidate and candidate.strip():
                        return [candidate.strip()]
            return []

        tokens = raw.split()
        out: list[str] = []
        seen: set[str] = set()
        for token in tokens:
            lookup = await _resolve_checkbl_token(token, server_id)
            if not lookup:
                continue
            key = lookup.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(lookup)
        return out

    @bot.on.message(text=dual("checkbl"))
    @requires_public
    async def checkbl_usage(
        message: Message,
        server_id: int = 0,
        access_level: int = 0,
    ) -> None:
        await message.answer(
            resp.error("/checkbl [ник / ID …]\n"
            "Пример: /checkbl Daniel_Bradberry\n"
            "Несколько: /cbl Nick_One Nick_Two 709801\n"
            "ID аккаунта — UUID с сервера, не VK.")
        )

    @bot.on.message(text=dual_with_args("checkbl", "<query>"))
    @requires_public
    async def checkbl_lookup(
        message: Message,
        query: str,
        server_id: int = 0,
        access_level: int = 0,
    ) -> None:
        lookups = await _resolve_checkbl_queries(message, query, server_id)
        if not lookups:
            await message.answer(
                resp.error("Укажите ник, ID аккаунта на сервере или @user.")
            )
            return
        if len(lookups) > CHECKBL_BATCH_MAX:
            await message.answer(
                resp.error(f"Максимум {CHECKBL_BATCH_MAX} ников или ID за раз.")
            )
            return
        for chunk in await check_blacklist_many(lookups):
            await message.answer(chunk, disable_mentions=1)

    @bot.on.message(text=dual("online"))
    @requires_level(0, command="online", require_registered=False)
    async def online_members(
        message: Message,
        server_id: int = 0,
        access_level: int = 0,
    ) -> None:
        if not _require_chat(message):
            await message.answer(resp.error("Команда только в беседах."))
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
                resp.error("/regdate [@user]\n"
                "Или ответом на сообщение.")
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
            await message.answer(resp.error("Пользователь не найден."))
            return
        text = await admin.format_registration_date(target_id)
        await message.answer(text, disable_mentions=1)

    @bot.on.message(text=dual("mute"))
    @requires_level(AccessLevel.SUPERVISOR, command="mute")
    async def mute_usage(
        message: Message,
        server_id: int = 0,
        access_level: int = 0,
    ) -> None:
        await message.answer(
            resp.error("/mute [@user] [время] [причина]\n"
            "Время: 30m, 1h, 2d\n"
            "Или ответом: /mute 30m спам")
        )

    @bot.on.message(text=dual_with_args("mute", "<args>"))
    @requires_level(AccessLevel.SUPERVISOR, command="mute")
    async def mute_user(
        message: Message,
        args: str,
        server_id: int = 0,
        access_level: int = 0,
    ) -> None:
        if not _require_chat(message):
            await message.answer(resp.error("Команда только в беседах."))
            return

        reason: str | None = None
        if message.reply_message and message.reply_message.from_id > 0:
            target_id = message.reply_message.from_id
            reply_parts = args.strip().split(maxsplit=1)
            if not reply_parts:
                await message.answer(resp.error("Ответом: /mute [время] [причина]"))
                return
            seconds = admin.parse_duration(reply_parts[0])
            if not seconds:
                await message.answer(resp.error("Укажите время: 30m, 1h, 2d"))
                return
            reason = reply_parts[1].strip() if len(reply_parts) > 1 else None
        else:
            target_raw, seconds, reason = admin.parse_mute_args(args)
            if not target_raw or not seconds:
                await message.answer(resp.error("/mute [@user] [время] [причина]"))
                return
            target_id = await _resolve_target(message, target_raw, server_id)
            if not target_id:
                await message.answer(resp.error("Пользователь не найден."))
                return

        if not seconds or seconds < 1:
            await message.answer(resp.error("Укажите время: 30m, 1h, 2d."))
            return

        actor_id = message.from_id or 0
        if target_id == actor_id:
            await message.answer(resp.error("Нельзя выдать мут самому себе."))
            return
        allowed, hier_err = await can_act_on_target(
            actor_id,
            access_level,
            target_id,
            server_id,
            on_equal_or_higher=(
                resp.error("Нельзя выдать мут пользователю своего уровня или выше.")
            ),
            on_developer=resp.error("Нельзя выдать мут разработчику."),
        )
        if not allowed:
            await message.answer(hier_err or resp.error("Недостаточно прав."))
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
            await message.answer(resp.error(f"Не удалось выдать мут.\n{err}"))

    @bot.on.message(text=dual("unmute"))
    @requires_level(AccessLevel.SUPERVISOR, command="unmute")
    async def unmute_usage(
        message: Message,
        server_id: int = 0,
        access_level: int = 0,
    ) -> None:
        await message.answer(resp.error("/unmute [@user] — или ответом на сообщение."))

    @bot.on.message(text=dual_with_args("unmute", "<target>"))
    @requires_level(AccessLevel.SUPERVISOR, command="unmute")
    async def unmute_user(
        message: Message,
        target: str,
        server_id: int = 0,
        access_level: int = 0,
    ) -> None:
        if not _require_chat(message):
            await message.answer(resp.error("Команда только в беседах."))
            return
        target_id = await _resolve_target(message, target, server_id)
        if not target_id:
            await message.answer(resp.error("Пользователь не найден."))
            return

        actor_id = message.from_id or 0
        if target_id == actor_id:
            await message.answer(resp.error("Нельзя снять мут с самого себя этой командой."))
            return
        allowed, hier_err = await can_act_on_target(
            actor_id,
            access_level,
            target_id,
            server_id,
            on_equal_or_higher=(
                resp.error("Нельзя снять мут с пользователя своего уровня или выше.")
            ),
            on_developer=resp.error("Нельзя снять мут с разработчика."),
        )
        if not allowed:
            await message.answer(hier_err or resp.error("Недостаточно прав."))
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
            await message.answer(resp.error(f"Не удалось снять мут.\n{err}"))

    @bot.on.message(text=dual("stitle"))
    @requires_level(AccessLevel.ZGS, command="stitle")
    async def stitle_usage(
        message: Message,
        server_id: int = 0,
        access_level: int = 0,
    ) -> None:
        await message.answer(resp.error("/stitle [новое название беседы]"))

    @bot.on.message(text=dual_with_args("stitle", "<title>"))
    @requires_level(AccessLevel.ZGS, command="stitle")
    async def set_title(
        message: Message,
        title: str,
        server_id: int = 0,
        access_level: int = 0,
    ) -> None:
        if not _require_chat(message):
            await message.answer(resp.error("Команда только в беседах."))
            return

        ok, result = await admin.set_chat_title(message.peer_id, title)
        if ok:
            chat = await ChatRepository.get_by_peer_id(message.peer_id)
            if chat:
                chat.title = result
                await chat.save()
            await message.answer(resp.success(f"Название беседы: «{result}»"))
            await action_logger.log_user(
                "stitle",
                message.from_id,
                result[:80],
                "Изменено",
                source_peer_id=message.peer_id,
            )
        else:
            await message.answer(resp.error(f"{result}"))

    @bot.on.message(text=dual("chatsettings"))
    @requires_level(AccessLevel.ZGS, command="chatsettings")
    async def show_settings(
        message: Message,
        server_id: int = 0,
        access_level: int = 0,
    ) -> None:
        if not _require_chat(message):
            await message.answer(resp.error("Команда только в беседах."))
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
        if not session:
            return False
        text = (message.text or "").strip()
        if not text.isdigit():
            return False
        number = int(text)
        if session.phase == "pick_setting":
            return number in {1, 2, 3, 4}
        if session.phase == "pick_kind":
            return 1 <= number <= len(KIND_PICK_ITEMS)
        if session.phase == "pick_sphere":
            from services.chat_kind import spheres_for_kind

            return 1 <= number <= len(spheres_for_kind(session.setting_key or ""))
        return False

    async def _apply_chat_kind_from_message(
        message: Message,
        *,
        kind: str,
        sphere: str | None,
        server_id: int,
    ) -> None:
        from services.chat_kind import apply_chat_kind, kind_label

        try:
            title = None
            chat = await ChatRepository.get_by_peer_id(message.peer_id)
            if chat:
                title = chat.title
            await apply_chat_kind(
                message.peer_id,
                kind,
                server_id=server_id,
                updated_by=message.from_id or 0,
                sphere=sphere,
                api=api,
                title=title,
            )
        except ValueError as exc:
            await message.answer(resp.error(f"{exc}"))
            return
        except Exception:
            logger.exception("apply_chat_kind failed peer=%s kind=%s", message.peer_id, kind)
            await message.answer(resp.error("Не удалось сменить тип беседы. Попробуйте ещё раз."))
            return
        clear_chat_settings_session(message.peer_id, message.from_id or 0)
        await message.answer(
            resp.success(f"Тип беседы: {kind_label(kind, sphere)}"),
            disable_mentions=1,
        )
        await action_logger.log_user(
            "chatsettings",
            message.from_id or 0,
            f"chatKind={kind}" + (f" sphere={sphere}" if sphere else ""),
            "Изменено",
            source_peer_id=message.peer_id,
        )

    @bot.on.message(FuncRule(_chat_settings_pick_rule), blocking=True)
    @requires_level(AccessLevel.ZGS, command="chatsettings")
    async def chat_settings_pick_number(
        message: Message,
        server_id: int = 0,
        access_level: int = 0,
    ) -> None:
        number = int((message.text or "").strip())
        owner_id = message.from_id or 0
        session = get_chat_settings_session(message.peer_id, owner_id)
        phase = session.phase if session else "pick_setting"

        if phase == "pick_kind":
            if not (1 <= number <= len(KIND_PICK_ITEMS)):
                await message.answer(resp.error("Нет такого типа. Укажите номер из списка."))
                return
            kind, _label = KIND_PICK_ITEMS[number - 1]
            from services.chat_kind import spheres_for_kind

            if spheres_for_kind(kind):
                start_pick_sphere(message.peer_id, owner_id, kind)
                await message.answer(format_sphere_pick_text(kind), disable_mentions=1)
                return
            await _apply_chat_kind_from_message(
                message, kind=kind, sphere=None, server_id=server_id
            )
            return

        if phase == "pick_sphere":
            from services.chat_kind import spheres_for_kind

            kind = session.setting_key if session else ""
            keys = list(spheres_for_kind(kind))
            if not kind or not (1 <= number <= len(keys)):
                await message.answer(resp.error("Нет такой сферы. Укажите номер из списка."))
                return
            await _apply_chat_kind_from_message(
                message, kind=kind, sphere=keys[number - 1], server_id=server_id
            )
            return

        if number == 4:
            start_pick_kind(message.peer_id, owner_id)
            await message.answer(format_kind_pick_text(), disable_mentions=1)
            return
        setting = CHAT_SETTINGS_BY_NUMBER.get(number)
        if not setting:
            await message.answer(resp.error("Нет такого пункта. Укажите 1, 2, 3 или 4."))
            return
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
            await event.show_snackbar(resp.error("Только в беседах."))
            return

        from middlewares.access import AccessChecker

        server_id = await AccessChecker.resolve_server_id(event.peer_id, event.user_id)
        if await AccessChecker.get_level(event.user_id, server_id) < AccessLevel.ZGS:
            await event.show_snackbar(resp.denied("Недостаточно прав."))
            return

        action = payload.get("action")
        peer_id = event.peer_id
        owner_id = payload.get("owner")

        if action in ("edit", "set", "kind", "ksphere") and not is_callback_owner(
            event.user_id, owner_id
        ):
            await event.show_snackbar(resp.denied("Только автор команды."))
            await event.send_empty_answer()
            return

        if action == "edit":
            start_pick_setting(peer_id, event.user_id)
            panel = await format_settings_edit_panel(api, peer_id)
            await event.send_message(panel, disable_mentions=1)
            await event.send_empty_answer()
            return

        if action in ("kpage", "kpage1"):
            await event.send_message(
                "⚙ Тип беседы\nВыберите тип:",
                keyboard=create_kind_keyboard(event.user_id, page=1 if action == "kpage1" else 2),
                disable_mentions=1,
            )
            await event.send_empty_answer()
            return

        if action in ("spage", "spage0"):
            kind = str(payload.get("k") or "")
            page = int(payload.get("p") or 0)
            from services.chat_kind import kind_label

            await event.send_message(
                f"⚙ {kind_label(kind)}\nВыберите сферу:",
                keyboard=create_sphere_keyboard(kind, event.user_id, page=page),
                disable_mentions=1,
            )
            await event.send_empty_answer()
            return

        if action == "kind":
            kind = str(payload.get("k") or "")
            from services.chat_kind import kind_label, spheres_for_kind

            if spheres_for_kind(kind):
                await event.send_message(
                    f"⚙ {kind_label(kind)}\nВыберите сферу:",
                    keyboard=create_sphere_keyboard(kind, event.user_id),
                    disable_mentions=1,
                )
                await event.send_empty_answer()
                return
            try:
                from services.chat_kind import apply_chat_kind

                title = None
                chat = await ChatRepository.get_by_peer_id(peer_id)
                if chat:
                    title = chat.title
                await apply_chat_kind(
                    peer_id,
                    kind,
                    server_id=server_id,
                    updated_by=event.user_id,
                    api=api,
                    title=title,
                )
            except ValueError as exc:
                await event.show_snackbar(resp.error(f"{exc}"))
                return
            except Exception:
                logger.exception("apply_chat_kind callback failed peer=%s", peer_id)
                await event.send_message(resp.error("Не удалось сменить тип беседы."))
                await event.send_empty_answer()
                return
            clear_chat_settings_session(peer_id, event.user_id)
            await event.send_message(
                resp.success(f"Тип беседы: {kind_label(kind)}"),
                disable_mentions=1,
            )
            await action_logger.log_user(
                "chatsettings",
                event.user_id,
                f"chatKind={kind}",
                "Изменено",
                source_peer_id=peer_id,
            )
            await event.send_empty_answer()
            return

        if action == "ksphere":
            kind = str(payload.get("k") or "")
            sphere = str(payload.get("s") or "")
            from services.chat_kind import apply_chat_kind, kind_label

            try:
                title = None
                chat = await ChatRepository.get_by_peer_id(peer_id)
                if chat:
                    title = chat.title
                await apply_chat_kind(
                    peer_id,
                    kind,
                    server_id=server_id,
                    updated_by=event.user_id,
                    sphere=sphere,
                    api=api,
                    title=title,
                )
            except ValueError as exc:
                await event.show_snackbar(resp.error(f"{exc}"))
                return
            except Exception:
                logger.exception("apply_chat_kind sphere failed peer=%s", peer_id)
                await event.send_message(resp.error("Не удалось сменить тип беседы."))
                await event.send_empty_answer()
                return
            clear_chat_settings_session(peer_id, event.user_id)
            await event.send_message(
                resp.success(f"Тип беседы: {kind_label(kind, sphere)}"),
                disable_mentions=1,
            )
            await action_logger.log_user(
                "chatsettings",
                event.user_id,
                f"chatKind={kind} sphere={sphere}",
                "Изменено",
                source_peer_id=peer_id,
            )
            await event.send_empty_answer()
            return

        if action == "set":
            field = payload.get("key")
            value = payload.get("value")
            setting = CHAT_SETTINGS.get(str(field or ""))
            if not setting or not value:
                await event.show_snackbar(resp.error("Некорректный запрос."))
                return
            try:
                await apply_setting(
                    peer_id,
                    setting.field,
                    str(value),
                    updated_by=event.user_id,
                )
            except ValueError as exc:
                await event.show_snackbar(resp.error(f"{exc}"))
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
        @requires_level(AccessLevel.ZGS, command="rejoinkick")
        async def _usage(
            message: Message,
            server_id: int = 0,
            access_level: int = 0,
            *,
            _cmd: str = cmd,
        ) -> None:
            await message.answer(resp.error(f"/{_cmd} on|off|ask"))

        @bot.on.message(text=dual_with_args(cmd, "<mode>"))
        @requires_level(AccessLevel.ZGS, command="rejoinkick")
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
                await message.answer(resp.error("Команда только в беседах."))
                return
            normalized = ChatSettingsRepository.normalize_mode(mode)
            if not normalized:
                await message.answer(resp.error("Режим: on, off или ask"))
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
            await message.answer(resp.success(f"/{_cmd} → {label}"))

    _register_rejoin("rejoinkick", "kick_on_leave")
