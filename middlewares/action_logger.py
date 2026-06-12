"""Логирование действий в беседу logs или ЛС администратора."""

from __future__ import annotations

import logging
import random
import re
from datetime import datetime

from vkbottle import API

from config.settings import DEFAULT_SERVER_ID, DEFAULT_SERVER_SLUG, LOG_CHAT_ID, MAIN_ADMIN_ID
from database.repository.chat_repo import ChatRepository
from database.repository.server_repo import ServerRepository
from database.repository.user_repo import UserRepository
from middlewares.access import AccessChecker
from services.display_name import DisplayNameService

logger = logging.getLogger(__name__)

_THREAD_ACTIONS = frozenset({
    "close_thread",
    "open_thread",
    "pin_thread",
    "unpin_thread",
    "thread_info",
    "toggle_open_close",
})

_USER_TARGET_ACTIONS = frozenset({
    "add_user",
    "remove_user",
    "make_admin",
    "make_judge",
    "add_court",
    "deluser",
    "kick",
    "poolkick",
    "setlevel",
    "setnick",
    "rnick",
    "remove_judge",
    "raccess",
    "setca",
    "set_speaker",
    "set_vice",
})

_ACTION_EMOJI: dict[str, str] = {
    "add_user": "➕",
    "remove_user": "➖",
    "make_admin": "👑",
    "make_judge": "⚖️",
    "add_court": "⚖️",
    "close_thread": "🔒",
    "open_thread": "🔓",
    "pin_thread": "📌",
    "unpin_thread": "📍",
    "thread_info": "ℹ️",
    "toggle_open_close": "🔒",
    "access_denied": "⛔",
    "thread_info_error": "⚠️",
    "kick": "🚫",
    "poolkick": "🚫",
    "setlevel": "🔐",
    "setnick": "✏️",
    "rnick": "✏️",
    "create_pool": "📂",
    "regchat": "💬",
    "pool_msg": "📢",
    "deluser": "🗑",
    "regcourt": "⚖️",
    "regsledca": "👁",
    "regcongress": "🏛",
    "ca_access_grant": "🏛",
    "ca_access_revoke": "🏛",
    "raccess": "🔓",
    "setca": "🏛",
    "unregchat": "📂",
    "remove_judge": "⚖️",
    "pin_message": "📌",
    "unpin_message": "📍",
    "delete_message": "🗑",
    "court_stats": "📊",
    "court_form_submit": "📄",
    "court_form_accept": "✅",
    "court_form_reject": "❌",
    "regchat_logs": "📋",
    "role_leave": "🔰",
    "set_speaker": "🎙",
    "set_vice": "🎖",
}

_ACTION_TITLES: dict[str, str] = {
    "kick": "Исключение из беседы",
    "poolkick": "Исключение из пула",
    "setlevel": "Изменение уровня",
    "setnick": "Установка никнейма",
    "rnick": "Снятие никнейма",
    "setca": "Доступ ЦА",
    "ca_access_grant": "Выдача доступа ЦА",
    "ca_access_revoke": "Снятие доступа ЦА",
    "raccess": "Снятие ролей",
    "add_court": "Назначение судьи",
    "remove_judge": "Снятие судьи",
    "deluser": "Удаление из БД",
    "regchat": "Регистрация беседы",
    "unregchat": "Отвязка беседы от пула",
    "regchat_logs": "Беседа логов",
    "create_pool": "Создание пула",
    "pool_msg": "Оповещение в пул",
    "regcourt": "Беседа судей",
    "regsledca": "Беседа след. ЦА",
    "regcongress": "Беседа конгресса",
    "set_speaker": "Спикер конгресса",
    "set_vice": "Вице-спикер конгресса",
    "pin_message": "Закрепление",
    "unpin_message": "Открепление",
    "delete_message": "Удаление сообщения",
    "close_thread": "Закрытие темы",
    "open_thread": "Открытие темы",
    "pin_thread": "Закрепление темы",
    "unpin_thread": "Открепление темы",
    "thread_info": "Инфо о теме",
    "court_stats": "Статистика исков",
    "court_form_submit": "Запись форм",
    "court_form_accept": "Принятие формы",
    "court_form_reject": "Отклонение формы",
    "role_leave": "Снятие роли при выходе",
    "access_denied": "Отказ в доступе",
    "thread_info_error": "Ошибка темы",
}

_VK_ID_RE = re.compile(r"\bid(\d+)\b", re.IGNORECASE)


class ActionLogger:
    def __init__(self, api: API) -> None:
        self.api = api
        self.names = DisplayNameService(api)

    async def _resolve_server_id(self, source_peer_id: int | None) -> int | None:
        if source_peer_id and source_peer_id >= 2_000_000_000:
            chat = await ChatRepository.get_by_peer_id(source_peer_id)
            if chat:
                return chat.server_id
        default = await ServerRepository.get_by_id(DEFAULT_SERVER_ID)
        if default:
            return default.id
        by_slug = await ServerRepository.get_by_slug(DEFAULT_SERVER_SLUG)
        return by_slug.id if by_slug else None

    async def _resolve_log_peer(self, source_peer_id: int | None = None) -> int | None:
        server_ids: list[int] = []
        if source_peer_id and source_peer_id >= 2_000_000_000:
            chat = await ChatRepository.get_by_peer_id(source_peer_id)
            if chat:
                server_ids.append(chat.server_id)

        default = await ServerRepository.get_by_id(DEFAULT_SERVER_ID)
        if not default:
            default = await ServerRepository.get_by_slug(DEFAULT_SERVER_SLUG)
        if default and default.id not in server_ids:
            server_ids.append(default.id)

        for server_id in server_ids:
            peer = await ServerRepository.get_log_peer_id(server_id)
            if peer:
                return peer

        fallback = MAIN_ADMIN_ID or LOG_CHAT_ID
        return fallback if fallback else None

    async def _short_user(self, vk_id: int, server_id: int | None = None) -> str:
        nick = await self.names.get_ping_nickname(vk_id, server_id)
        full = await self.names.get_vk_full_name(vk_id)
        label = nick or full
        parts = [f"{label} (id{vk_id})"]
        if server_id:
            level = await UserRepository.get_access_level(vk_id, server_id)
            if level:
                parts.append(AccessChecker.level_name(level))
        return " · ".join(parts)

    async def format_user(self, vk_id: int, server_id: int | None = None) -> str:
        return await self._short_user(vk_id, server_id)

    async def _enrich_ids_in_text(
        self,
        text: str,
        server_id: int | None,
    ) -> str:
        if not text:
            return "—"

        seen: set[int] = set()

        async def _replace(match: re.Match[str]) -> str:
            vk_id = int(match.group(1))
            if vk_id in seen:
                return match.group(0)
            seen.add(vk_id)
            return await self._short_user(vk_id, server_id)

        result = text
        for match in list(_VK_ID_RE.finditer(text)):
            replacement = await _replace(match)
            result = result.replace(match.group(0), replacement, 1)
        return result

    @staticmethod
    def _split_target_and_extra(target_info: str) -> tuple[str, str | None]:
        lowered = target_info.lower()
        for sep in (", причина:", ", пул ", ", алиас "):
            idx = lowered.find(sep)
            if idx != -1:
                main = target_info[:idx].strip()
                extra = target_info[idx + 1 :].strip()
                return main, extra
        if " → " in target_info:
            main, extra = target_info.split(" → ", 1)
            return main.strip(), extra.strip()
        return target_info.strip(), None

    async def _source_label(self, source_peer_id: int | None) -> str:
        if not source_peer_id or source_peer_id < 2_000_000_000:
            return "ЛС бота"

        chat_id = source_peer_id - 2_000_000_000
        chat = await ChatRepository.get_by_peer_id(source_peer_id)
        if not chat:
            return f"Беседа #{chat_id}"

        await chat.fetch_related("pool", "server")
        title = (chat.title or "").strip() or f"Беседа #{chat_id}"
        parts = [title, f"#{chat_id}"]
        if chat.alias:
            parts.append(f"алиас «{chat.alias}»")
        if chat.pool:
            parts.append(f"пул «{chat.pool.name}»")
        if chat.server:
            parts.append(chat.server.name)
        return " · ".join(parts)

    @staticmethod
    def _action_title(action: str) -> str:
        return _ACTION_TITLES.get(action, action.replace("_", " ").capitalize())

    @staticmethod
    def _result_icon(result: str) -> str:
        low = result.lower()
        if low.startswith("ошибка") or "не найден" in low or "не удалось" in low:
            return "❌"
        return "✅"

    def _build_message(
        self,
        action: str,
        user_info: str,
        target_info: str,
        result: str,
        *,
        source: str,
        extra: str | None = None,
    ) -> str:
        timestamp = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
        emoji = _ACTION_EMOJI.get(action, "📌")
        title = self._action_title(action)
        result_icon = self._result_icon(result)

        actor_label = "Кто" if action in _USER_TARGET_ACTIONS else "Пользователь"
        lines = [
            f"{emoji} {title}",
            "━━━━━━━━━━━━━━━━",
            f"👤 {actor_label}: {user_info}",
            f"📍 Где: {source}",
        ]

        if action in _USER_TARGET_ACTIONS:
            lines.append(f"🎯 Цель: {target_info}")
        elif action in _THREAD_ACTIONS:
            lines.append(f"🔗 Тема: {target_info}")
        else:
            lines.append(f"📝 Детали: {target_info}")

        if extra:
            lines.append(f"📎 {extra}")

        lines.extend(
            [
                f"{result_icon} Итог: {result}",
                f"🕐 {timestamp}",
            ]
        )
        return "\n".join(lines)

    async def log_action(
        self,
        action: str,
        user_info: str,
        target_info: str,
        result: str,
        *,
        source_peer_id: int | None = None,
    ) -> None:
        log_peer = await self._resolve_log_peer(source_peer_id)
        if not log_peer:
            return

        msg = self._build_message(
            action,
            user_info,
            target_info,
            result,
            source=await self._source_label(source_peer_id),
        )
        try:
            await self.api.messages.send(
                peer_id=log_peer,
                message=msg,
                random_id=random.randint(1, 2_000_000_000),
                disable_mentions=1,
            )
        except Exception as exc:
            logger.error("Ошибка отправки лога: %s", exc)

    async def log_user(
        self,
        action: str,
        user_id: int,
        target_info: str,
        result: str,
        *,
        source_peer_id: int | None = None,
    ) -> None:
        server_id = await self._resolve_server_id(source_peer_id)
        user_info = await self._short_user(user_id, server_id)

        main, extra = self._split_target_and_extra(target_info)
        main = await self._enrich_ids_in_text(main, server_id)
        if extra:
            extra = await self._enrich_ids_in_text(extra, server_id)

        log_peer = await self._resolve_log_peer(source_peer_id)
        if not log_peer:
            return

        msg = self._build_message(
            action,
            user_info,
            main,
            result,
            source=await self._source_label(source_peer_id),
            extra=extra,
        )
        try:
            await self.api.messages.send(
                peer_id=log_peer,
                message=msg,
                random_id=random.randint(1, 2_000_000_000),
                disable_mentions=1,
            )
        except Exception as exc:
            logger.error("Ошибка отправки лога: %s", exc)

    async def log(
        self,
        action: str,
        user_info: str,
        details: str,
        result: str,
        source_peer_id: int | None = None,
    ) -> None:
        await self.log_action(
            action,
            user_info,
            details,
            result,
            source_peer_id=source_peer_id,
        )
