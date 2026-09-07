"""Команды Академии следящих: профиль, задания, сдача, рейтинг."""

from __future__ import annotations

import logging
import re

from vkbottle import API
from vkbottle.bot import Bot, Message
from vkbottle.dispatch.rules.base import FuncRule

from database.models.user import AccessLevel
from middlewares.access import requires_level
from middlewares.action_logger import ActionLogger
from services import responses as resp
from services.command_utils import matches_cmd, strip_cmd
from services.panel_client import (
    academy_leaderboard,
    academy_me,
    academy_student,
    academy_submit_report,
    panel_api_configured,
)
from services.vk_resolver import VKResolver

logger = logging.getLogger(__name__)


def _cadet_card(cadet: dict) -> str:
    metrics = cadet.get("metrics") or {}
    lines = [
        f"{cadet.get('nickname') or 'Академик'}",
        f"Статус: {cadet.get('display_status') or '—'}",
        f"Направление: {cadet.get('direction_label') or '—'}",
        f"Этап: {cadet.get('stage_label') or '—'}",
        f"Наставник: {cadet.get('mentor_name') or 'не назначен'}",
        f"Прогресс: {metrics.get('progress', 0)}%",
        f"Рейтинг: {metrics.get('rating', 0)}/100",
        f"Задания: {metrics.get('assignments_done', 0)}/{metrics.get('assignments_total', 0)}",
        f"Просрочено: {metrics.get('overdue', 0)}",
        f"Посещаемость: {metrics.get('attendance_pct') if metrics.get('attendance_pct') is not None else '—'}%",
    ]
    rec = cadet.get("recommendation_label")
    if cadet.get("recommendation") and cadet.get("recommendation") != "none" and rec:
        lines.append(rec)
    return "\n".join(lines)


def register_academy(bot: Bot, api: API, action_logger: ActionLogger) -> None:
    del action_logger

    @bot.on.message(FuncRule(lambda m: matches_cmd(m.text or "", "academy")))
    @requires_level(AccessLevel.SUPERVISOR)
    async def academy_cmd(message: Message, server_id: int = 0, access_level: int = 0):
        del access_level
        if not panel_api_configured():
            await message.answer(resp.error("Панель академии не настроена."))
            return
        args = strip_cmd(message.text or "", "academy").strip()
        sub, _, rest = args.partition(" ")
        sub = sub.lower()
        if sub.isdigit():
            rest = f"{sub} {rest}".strip()
            sub = "submit"

        if not sub or sub in {"profile", "me", "я"}:
            ok, data = await academy_me(message.from_id, server_id)
            if not ok:
                await message.answer(resp.error(str(data)))
                return
            cadet = data.get("cadet") if isinstance(data, dict) else None
            if cadet:
                await message.answer(resp.ok(_cadet_card(cadet)))
                return
            roster = data.get("roster") if isinstance(data, dict) else None
            if roster:
                lines = ["Состав Академии:"]
                for row in roster:
                    lines.append(
                        f"• {row.get('nickname')} — {row.get('stage_label')} · {row.get('metrics', {}).get('rating', 0)}"
                    )
                await message.answer(resp.ok("\n".join(lines)))
                return
            await message.answer(resp.error("Вы не состоите в Академии. Зачисление — в карточке следящего на сайте."))
            return

        if sub in {"tasks", "task", "задания"}:
            ok, data = await academy_me(message.from_id, server_id)
            if not ok:
                await message.answer(resp.error(str(data)))
                return
            cadet = data.get("cadet") if isinstance(data, dict) else None
            opens = (cadet or {}).get("open_assignments") or []
            if not opens:
                await message.answer(resp.ok("Открытых заданий нет."))
                return
            lines = ["Задания Академии:"]
            for item in opens:
                due = (item.get("due_at") or "")[:10] or "—"
                lines.append(f"#{item.get('id')} {item.get('title')} · до {due}")
            lines.append("Сдать: /academy submit <id> текст")
            await message.answer(resp.ok("\n".join(lines)))
            return

        if sub in {"submit", "сдать", "areport"}:
            match = re.match(r"^(\d+)\s*(.*)$", rest.strip(), re.DOTALL)
            if not match:
                await message.answer(resp.error("/academy submit <id> текст отчёта"))
                return
            assignment_id = int(match.group(1))
            body = (match.group(2) or "").strip()
            if message.reply_message and not body:
                body = (message.reply_message.text or "").strip()
            ok, data = await academy_submit_report(message.from_id, assignment_id, server_id, body)
            if not ok:
                await message.answer(resp.error(str(data)))
                return
            await message.answer(resp.ok(f"Отчёт по заданию #{assignment_id} отправлен на проверку."))
            return

        if sub in {"leaderboard", "top", "рейтинг"}:
            ok, data = await academy_leaderboard(message.from_id, server_id)
            if not ok:
                await message.answer(resp.error(str(data)))
                return
            members = data.get("members") if isinstance(data, dict) else []
            if not members:
                await message.answer(resp.ok("Пока нет академиков в рейтинге."))
                return
            lines = ["Топ Академии:"]
            for i, row in enumerate(members, start=1):
                lines.append(
                    f"{i}. {row.get('nickname')} — {row.get('metrics', {}).get('rating', 0)} · {row.get('progress', row.get('metrics', {}).get('progress', 0))}%"
                )
            await message.answer(resp.ok("\n".join(lines)))
            return

        if sub in {"student", "card", "кто"}:
            reply_id = message.reply_message.from_id if message.reply_message else None
            resolver = VKResolver(api, server_id)
            resolved, hint = await resolver.resolve_from_message_with_hint(
                rest,
                reply_from_id=reply_id,
                server_id=server_id,
            )
            if hint:
                await message.answer(hint, disable_mentions=1)
                return
            if not resolved:
                await message.answer(resp.error("/academy student @user"))
                return
            ok, data = await academy_student(message.from_id, int(resolved.vk_id), server_id)
            if not ok:
                await message.answer(resp.error(str(data)))
                return
            cadet = data.get("cadet") if isinstance(data, dict) else None
            if not cadet:
                await message.answer(resp.error("Академик не найден."))
                return
            await message.answer(resp.ok(_cadet_card(cadet)))
            return

        await message.answer(
            resp.error(
                "/academy — свой прогресс\n"
                "/academy tasks — задания\n"
                "/academy submit <id> текст\n"
                "/academy leaderboard — рейтинг\n"
                "/academy student @user — карточка"
            )
        )
