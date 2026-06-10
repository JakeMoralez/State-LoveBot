"""Форум: info/edit, f-команды, иски."""

from __future__ import annotations

import json
import logging
import re
import time

from vkbottle import API, GroupEventType
from vkbottle.bot import Bot, Message, MessageEvent
from vkbottle.dispatch.rules.base import FuncRule

from database.repository.forum_role_repo import ForumRoleRepository
from database.repository.server_repo import ServerRepository
from middlewares.access import AccessChecker
from middlewares.action_logger import ActionLogger
from middlewares.forum_access import ForumAccessChecker, requires_forum_user
from services.command_utils import matches_cmd, parse_forum_thread, strip_cmd
from services.forum_api import ForumService
from services.forum_format import format_thread_card
from services.forum_keyboard import create_thread_action_keyboard
from services.server_display import format_judge_forum_hint

logger = logging.getLogger(__name__)

_FORUM_CALLBACK_CMDS = frozenset({"close", "open", "pin", "unpin"})

_ACTION_OK: dict[str, tuple[str, str]] = {
    "close": ("🔒", "Тема закрыта"),
    "open": ("🔓", "Тема открыта"),
    "pin": ("📌", "Тема закреплена"),
    "unpin": ("📍", "Тема откреплена"),
}

_ISKI_DAYS_RE = re.compile(
    r"^(?:дни?|days?|d)\s*(\d+)$|"
    r"^(\d+)\s*(?:д|d|дн(?:ей|я)?|days?)$",
    re.IGNORECASE,
)


def _parse_iski_arg(arg: str) -> tuple[str, int] | str:
    """('pages'|'days', value) или строка ошибки."""
    raw = (arg or "").strip()
    if not raw:
        return "pages", 1

    day_match = _ISKI_DAYS_RE.match(raw.lower())
    if day_match:
        days = int(day_match.group(1) or day_match.group(2))
        if days < 1 or days > 365:
            return "Укажите число дней от 1 до 365."
        return "days", days

    parts = raw.split()
    if parts[0].lower() in ("дни", "дней", "дня", "days", "day", "d"):
        if len(parts) < 2:
            return "Использование: /иски [страницы 1–20] или /иски [дни 1–365]"
        try:
            days = int(parts[1])
        except ValueError:
            return "Количество дней должно быть числом."
        if days < 1 or days > 365:
            return "Укажите число дней от 1 до 365."
        return "days", days

    try:
        pages = int(parts[0])
    except ValueError:
        return "Использование: /иски [страницы 1–20] или /иски 30д"
    if pages < 1 or pages > 20:
        return "Укажите число страниц от 1 до 20."
    return "pages", pages


_FCMD_OK: dict[str, tuple[str, str]] = {
    "fclose": ("🔒", "Тема закрыта"),
    "fopen": ("🔓", "Тема открыта"),
    "fpin": ("📌", "Тема закреплена"),
    "funpin": ("📍", "Тема откреплена"),
}

_FCMD_LOG: dict[str, tuple[str, str]] = {
    "fclose": ("close_thread", "Закрыта"),
    "fopen": ("open_thread", "Открыта"),
    "fpin": ("pin_thread", "Закреплена"),
    "funpin": ("unpin_thread", "Откреплена"),
}

_CALLBACK_LOG: dict[str, tuple[str, str]] = {
    "close": ("close_thread", "Закрыта"),
    "open": ("open_thread", "Открыта"),
    "pin": ("pin_thread", "Закреплена"),
    "unpin": ("unpin_thread", "Откреплена"),
}


def register_forum(
    bot: Bot,
    api: API,
    action_logger: ActionLogger,
    forum_service: ForumService | None = None,
) -> None:
    forum = forum_service or ForumService()

    async def _reply_not_ready(target: Message | MessageEvent, text: str) -> None:
        if isinstance(target, MessageEvent):
            await target.send_message(text)
            await target.send_empty_answer()
        else:
            await target.answer(text)

    async def _forum_not_ready(target: Message | MessageEvent) -> bool:
        if not forum.available:
            await _reply_not_ready(
                target,
                "⚠️ Форум не настроен.\n"
                "Заполните FORUM_XF_USER и FORUM_XF_SESSION в .env.",
            )
            return True
        if not forum.backend:
            await _reply_not_ready(
                target,
                "⚠️ Форум не подключён при старте.\n"
                "Перезапустите бота. Нужны cookies с forum.arizona-rp.com.",
            )
            return True
        return False

    async def _check_access(
        user_id: int,
        peer_id: int,
        category_id: int,
        server_id: int,
        reply,
    ) -> bool:
        if category_id and not await ForumAccessChecker.is_thread_allowed(
            user_id, int(category_id), server_id
        ):
            await reply("⛔ Нет доступа к разделу форума.")
            return False
        return True

    async def _check_judge_forum(
        category_id: int,
        server_id: int,
        reply,
    ) -> bool:
        judge_forum_id = await ServerRepository.get_judge_forum_id(server_id)
        if not judge_forum_id:
            await reply("⛔ Раздел судебных исков не настроен для этого сервера.")
            return False
        if category_id != judge_forum_id:
            await reply(
                "⛔ Команда только для раздела судебных исков "
                f"({format_judge_forum_hint(judge_forum_id)})."
            )
            return False
        return True

    @bot.on.message(FuncRule(lambda m: matches_cmd(m.text or "", "info") or matches_cmd(m.text or "", "edit")))
    @requires_forum_user
    async def thread_info_or_edit(message: Message, server_id: int = 0) -> None:
        if await _forum_not_ready(message):
            return

        thread_id = parse_forum_thread(message.text or "", ("info", "edit"))
        if not thread_id:
            await message.answer(
                "❌ Использование: /info или /edit [ссылка/id темы]\n"
                "Пример: /info https://forum.arizona-rp.com/threads/11103806/"
            )
            return

        info = await forum.get_thread_info(thread_id)
        if not info:
            await message.answer(
                f"❌ Тема {thread_id} не найдена или нет прав на просмотр."
            )
            return

        category_id = int(info.get("category_id") or info.get("node_id") or 0)
        if not await _check_judge_forum(
            category_id, server_id, message.answer
        ):
            return

        if not await _check_access(
            message.from_id, message.peer_id, category_id, server_id, message.answer
        ):
            return

        card = format_thread_card(info)
        keyboard = create_thread_action_keyboard(thread_id, message.from_id)
        await message.answer(f"{card}\n\n👇 Выбери действие:", keyboard=keyboard)
        title = (info.get("title") or "")[:50]
        await action_logger.log_user(
            "thread_info",
            message.from_id,
            f"Тема {thread_id}" + (f": {title}..." if title else ""),
            "Успешно",
            source_peer_id=message.peer_id,
        )

    async def _run_judge_thread_cmd(
        message: Message,
        *,
        server_id: int,
        cmd: str,
        action,
    ) -> None:
        if await _forum_not_ready(message):
            return

        arg = strip_cmd(message.text or "", cmd)
        thread_id = ForumService.parse_thread_id(arg) if arg else None
        if not thread_id:
            await message.answer(
                f"❌ Использование: /{cmd} или !{cmd} [ссылка/id темы]"
            )
            return

        info = await forum.get_thread_info(thread_id)
        if not info:
            await message.answer(f"❌ Тема {thread_id} не найдена.")
            return

        category_id = int(info.get("category_id") or info.get("node_id") or 0)
        if not await _check_judge_forum(
            category_id, server_id, message.answer
        ):
            return

        if not await _check_access(
            message.from_id, message.peer_id, category_id, server_id, message.answer
        ):
            return

        ok, err = await action(thread_id)
        if ok:
            emoji, text = _FCMD_OK[cmd]
            await message.answer(f"{emoji} {text}")
            log_action, log_result = _FCMD_LOG[cmd]
            await action_logger.log_user(
                log_action,
                message.from_id,
                f"Тема {thread_id}",
                log_result,
                source_peer_id=message.peer_id,
            )
        else:
            await message.answer(f"❌ {err or 'Ошибка'}")
            log_action, _ = _FCMD_LOG[cmd]
            await action_logger.log_user(
                log_action,
                message.from_id,
                f"Тема {thread_id}",
                f"Ошибка: {(err or 'неизвестно')[:80]}",
                source_peer_id=message.peer_id,
            )

    for _cmd, _action in (
        ("fclose", lambda tid: forum.set_thread_open(tid, False)),
        ("fopen", lambda tid: forum.set_thread_open(tid, True)),
        ("fpin", lambda tid: forum.set_thread_sticky(tid, True)),
        ("funpin", lambda tid: forum.set_thread_sticky(tid, False)),
    ):
        @bot.on.message(FuncRule(lambda m, c=_cmd: matches_cmd(m.text or "", c)))
        @requires_forum_user
        async def _f_handler(
            message: Message,
            server_id: int = 0,
            *,
            _c: str = _cmd,
            _a=_action,
        ) -> None:
            await _run_judge_thread_cmd(message, server_id=server_id, cmd=_c, action=_a)

    @bot.on.message(FuncRule(lambda m: matches_cmd(m.text or "", "иски")))
    @requires_forum_user
    async def court_stats(message: Message, server_id: int = 0) -> None:
        if await _forum_not_ready(message):
            return

        arg = strip_cmd(message.text or "", "иски")
        parsed = _parse_iski_arg(arg)
        if isinstance(parsed, str):
            await message.answer(
                f"❌ {parsed}\n"
                "Примеры: /иски 5 · /иски 30д · /иски дни 14"
            )
            return

        mode, value = parsed
        await message.answer("⚙️ Загрузка статистики исков...")
        judge_forum_id = await ServerRepository.get_judge_forum_id(server_id)
        if not judge_forum_id:
            await message.answer("⛔ Раздел судебных исков не настроен для этого сервера.")
            return
        if mode == "days":
            report = await forum.get_court_stats(
                server_id=server_id,
                judge_forum_id=judge_forum_id,
                days=value,
            )
        else:
            report = await forum.get_court_stats(
                server_id=server_id,
                judge_forum_id=judge_forum_id,
                pages=value,
            )
        await message.answer(report)

    @bot.on.raw_event(GroupEventType.MESSAGE_EVENT, MessageEvent, blocking=False)
    async def forum_thread_callback(event: MessageEvent) -> None:
        payload = event.payload
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                return
        if not isinstance(payload, dict):
            return

        cmd = payload.get("cmd")
        if cmd not in _FORUM_CALLBACK_CMDS:
            return

        if not await ForumRoleRepository.can_use_forum_bot(event.user_id):
            await event.show_snackbar("⛔ Нет доступа к боту.")
            return

        if await _forum_not_ready(event):
            return

        thread_id = payload.get("thread_id")
        creator_id = payload.get("creator_id")
        created_at = payload.get("created_at")
        if not thread_id:
            await event.show_snackbar("❌ ID темы не найден")
            return

        if created_at and int(time.time()) - int(created_at) > 300:
            await event.send_message(
                "⏰ Время действия кнопок истекло. Используй /edit заново."
            )
            await event.send_empty_answer()
            return
        if event.user_id != creator_id:
            await event.show_snackbar("⛔ Кнопки доступны только автору команды.")
            return

        server_id = await AccessChecker.resolve_server_id(event.peer_id, event.user_id)

        info = await forum.get_thread_info(int(thread_id))
        if not info:
            await event.show_snackbar(f"❌ Тема {thread_id} не найдена")
            return

        category_id = int(info.get("category_id") or info.get("node_id") or 0)
        judge_forum_id = await ServerRepository.get_judge_forum_id(server_id)
        if not judge_forum_id:
            await event.show_snackbar("⛔ Раздел исков не настроен для сервера")
            return
        if category_id != judge_forum_id:
            await event.show_snackbar(
                f"⛔ Только раздел {format_judge_forum_hint(judge_forum_id)}"
            )
            return
        if not await ForumAccessChecker.is_thread_allowed(
            event.user_id, category_id, server_id
        ):
            await event.show_snackbar("⛔ Нет доступа к разделу форума.")
            return

        try:
            if cmd == "close":
                ok, msg = await forum.set_thread_open(int(thread_id), False)
            elif cmd == "open":
                ok, msg = await forum.set_thread_open(int(thread_id), True)
            elif cmd == "pin":
                ok, msg = await forum.set_thread_sticky(int(thread_id), True)
            else:
                ok, msg = await forum.set_thread_sticky(int(thread_id), False)

            if ok:
                emoji, text = _ACTION_OK[cmd]
                await event.send_message(f"{emoji} {text} (тема {thread_id})")
                log_action, log_result = _CALLBACK_LOG[cmd]
                await action_logger.log_user(
                    log_action,
                    event.user_id,
                    f"Тема {thread_id}",
                    log_result,
                    source_peer_id=event.peer_id,
                )
            else:
                await event.send_message(f"❌ {msg or 'Ошибка'}")
                log_action, _ = _CALLBACK_LOG[cmd]
                await action_logger.log_user(
                    log_action,
                    event.user_id,
                    f"Тема {thread_id}",
                    f"Ошибка: {(msg or 'неизвестно')[:80]}",
                    source_peer_id=event.peer_id,
                )
            await event.send_empty_answer()
        except Exception as exc:
            logger.exception("forum callback %s: %s", cmd, exc)
            await event.show_snackbar("❌ Ошибка при действии с темой")
            if cmd in _CALLBACK_LOG:
                log_action, _ = _CALLBACK_LOG[cmd]
                await action_logger.log_user(
                    log_action,
                    event.user_id,
                    f"Тема {thread_id}",
                    f"Ошибка: {str(exc)[:80]}",
                    source_peer_id=event.peer_id,
                )
