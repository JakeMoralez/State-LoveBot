"""Логирование действий в личку администратора (как legacy/logger.py)."""

from __future__ import annotations

import logging
import random
from datetime import datetime

from vkbottle import API

from config.settings import LOG_CHAT_ID, MAIN_ADMIN_ID
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
    "create_pool": "📂",
    "regchat": "💬",
    "pool_msg": "📢",
    "deluser": "➖",
    "regcourt": "⚖️",
    "regsledca": "👁",
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
}


class ActionLogger:
    def __init__(self, api: API) -> None:
        self.api = api
        self.names = DisplayNameService(api)
        self._log_peer = MAIN_ADMIN_ID or LOG_CHAT_ID

    async def format_user(self, vk_id: int) -> str:
        """Формат: Имя Фамилия (id123456)."""
        try:
            name = await self.names.get_vk_full_name(vk_id)
            if name and not name.startswith("id"):
                return f"{name} (id{vk_id})"
        except Exception:
            pass
        return f"id{vk_id}"

    @staticmethod
    def _source_label(source_peer_id: int | None) -> str:
        if source_peer_id and source_peer_id >= 2_000_000_000:
            return f"Беседа #{source_peer_id - 2_000_000_000}"
        return "Личные сообщения"

    @staticmethod
    def _action_title(action: str) -> str:
        return action.replace("_", " ").title()

    def _build_message(
        self,
        action: str,
        user_info: str,
        target_info: str,
        result: str,
        source_peer_id: int | None,
    ) -> str:
        timestamp = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
        source = self._source_label(source_peer_id)
        emoji = _ACTION_EMOJI.get(action, "📌")
        title = self._action_title(action)

        if action in _USER_TARGET_ACTIONS:
            body = (
                f"👤 Пользователь: {user_info}\n"
                f"📍 Источник: {source}\n"
                f"🎯 Цель: {target_info}\n"
                f"✅ Результат: {result}\n"
                f"🕐 Время: {timestamp}"
            )
        elif action in _THREAD_ACTIONS:
            body = (
                f"👤 Пользователь: {user_info}\n"
                f"📍 Источник: {source}\n"
                f"🔗 Тема: {target_info}\n"
                f"✅ Результат: {result}\n"
                f"🕐 Время: {timestamp}"
            )
        elif action in ("access_denied", "thread_info_error"):
            body = (
                f"👤 Пользователь: {user_info}\n"
                f"📍 Источник: {source}\n"
                f"📝 Детали: {target_info}\n"
                f"✅ Результат: {result}\n"
                f"🕐 Время: {timestamp}"
            )
        else:
            body = (
                f"👤 Пользователь: {user_info}\n"
                f"📍 Источник: {source}\n"
                f"📝 Детали: {target_info}\n"
                f"✅ Результат: {result}\n"
                f"🕐 Время: {timestamp}"
            )

        return f"{emoji} {title}\n━━━━━━━━━━━━━━━━\n{body}"

    async def log_action(
        self,
        action: str,
        user_info: str,
        target_info: str,
        result: str,
        *,
        source_peer_id: int | None = None,
    ) -> None:
        if not self._log_peer:
            return

        msg = self._build_message(
            action, user_info, target_info, result, source_peer_id
        )
        try:
            await self.api.messages.send(
                peer_id=self._log_peer,
                message=msg,
                random_id=random.randint(1, 2_000_000_000),
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
        user_info = await self.format_user(user_id)
        await self.log_action(
            action,
            user_info,
            target_info,
            result,
            source_peer_id=source_peer_id,
        )

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
