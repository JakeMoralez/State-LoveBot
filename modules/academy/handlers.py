"""Команды Академии следящих: профиль, задания, сдача."""

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
    academy_me,
    academy_student,
    academy_submit_report,
    panel_api_configured,
)
from services.vk_resolver import VKResolver

logger = logging.getLogger(__name__)

_URL_RE = re.compile(r"https?://[^\s<>]+", re.IGNORECASE)


def _cadet_card(cadet: dict) -> str:
    metrics = cadet.get("metrics") or {}
    avg = metrics.get("average_score")
    avg_label = f"{avg}/10" if avg is not None else "—"
    lines = [
        f"{cadet.get('nickname') or 'Академик'}",
        f"Статус: {cadet.get('display_status') or '—'}",
        f"Направление: {cadet.get('direction_label') or '—'}",
        f"Этап: {cadet.get('stage_label') or '—'}",
        f"Наставник: {cadet.get('mentor_name') or 'не назначен'}",
        f"Задания: {metrics.get('assignments_done', 0)}/{metrics.get('assignments_total', 0)}",
        f"Просрочено: {metrics.get('overdue', 0)}",
        f"Средняя оценка: {avg_label}",
        (
            "Прогресс этапа: "
            f"{metrics.get('stage_required_done', 0)}/{metrics.get('stage_required_total', 0)} обяз."
        ),
    ]
    rec = cadet.get("recommendation_label")
    if cadet.get("recommendation") and cadet.get("recommendation") != "none" and rec:
        lines.append(rec)
    return "\n".join(lines)


def _open_tasks_text(opens: list) -> str:
    if not opens:
        return "Открытых заданий нет."
    lines = ["Открытые задания:"]
    for item in opens:
        due = (item.get("due_at") or "")[:10] or "—"
        status = item.get("viewer_status_label") or "Не сдано"
        lines.append(f"#{item.get('id')} {item.get('title')} · {status} · до {due}")
    lines.append("Сдать: /academy submit <id> текст")
    lines.append("Можно ответить на сообщение или приложить фото.")
    return "\n".join(lines)


def _proof_urls_from_message(message: Message) -> list[str]:
    urls: list[str] = []
    sources = [message]
    reply = getattr(message, "reply_message", None)
    if reply is not None:
        sources.append(reply)
    for src in sources:
        for att in getattr(src, "attachments", None) or []:
            photo = getattr(att, "photo", None)
            sizes = getattr(photo, "sizes", None) if photo is not None else None
            if sizes:
                best = max(
                    sizes,
                    key=lambda s: (getattr(s, "width", 0) or 0) * (getattr(s, "height", 0) or 0),
                )
                url = getattr(best, "url", None)
                if url:
                    urls.append(str(url))
            doc = getattr(att, "doc", None)
            if doc is not None:
                url = getattr(doc, "url", None)
                if url:
                    urls.append(str(url))
            link = getattr(att, "link", None)
            if link is not None:
                url = getattr(link, "url", None)
                if url:
                    urls.append(str(url))
        try:
            strings = src.get_attachment_strings() or []
        except Exception:
            strings = []
        for item in strings:
            if item.startswith("photo") or item.startswith("doc"):
                urls.append(f"https://vk.com/{item}")
        text = getattr(src, "text", None) or ""
        urls.extend(_URL_RE.findall(text))
    seen: set[str] = set()
    out: list[str] = []
    for url in urls:
        clean = url.rstrip(").,;")
        if clean not in seen:
            seen.add(clean)
            out.append(clean)
    return out


def register_academy(bot: Bot, api: API, action_logger: ActionLogger) -> None:
    del action_logger

    @bot.on.message(FuncRule(lambda m: matches_cmd(m.text or "", "academy")))
    @requires_level(AccessLevel.PGS)
    async def academy_cmd(message: Message, server_id: int = 0, access_level: int = 0):
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
                    avg = (row.get("metrics") or {}).get("average_score")
                    score = f"{avg}/10" if avg is not None else "—"
                    lines.append(f"• {row.get('nickname')} — {row.get('stage_label')} · {score}")
                await message.answer(resp.ok("\n".join(lines)))
                return
            await message.answer(
                resp.error("Вы не состоите в Академии. Зачисление — в карточке следящего на сайте.")
            )
            return

        if sub in {"tasks", "task", "задания"}:
            ok, data = await academy_me(message.from_id, server_id)
            if not ok:
                await message.answer(resp.error(str(data)))
                return
            cadet = data.get("cadet") if isinstance(data, dict) else None
            opens = (cadet or {}).get("open_assignments") or []
            await message.answer(resp.ok(_open_tasks_text(opens)))
            return

        if sub in {"submit", "сдать", "areport"}:
            match = re.match(r"^(\d+)\s*(.*)$", rest.strip(), re.DOTALL)
            if not match:
                ok, data = await academy_me(message.from_id, server_id)
                if not ok:
                    await message.answer(resp.error(str(data)))
                    return
                cadet = data.get("cadet") if isinstance(data, dict) else None
                opens = (cadet or {}).get("open_assignments") or []
                await message.answer(resp.ok(_open_tasks_text(opens)))
                return
            assignment_id = int(match.group(1))
            body = (match.group(2) or "").strip()
            if message.reply_message and not body:
                body = (message.reply_message.text or "").strip()
            proof_urls = _proof_urls_from_message(message)
            if not body and not proof_urls:
                await message.answer(
                    resp.error("Напишите текст, ответьте на сообщение или приложите фото.")
                )
                return
            ok, data = await academy_submit_report(
                message.from_id,
                assignment_id,
                server_id,
                body,
                proof_urls,
            )
            if not ok:
                await message.answer(resp.error(str(data)))
                return
            await message.answer(resp.ok(f"Отчёт по заданию #{assignment_id} отправлен на проверку."))
            return

        if sub in {"leaderboard", "top", "рейтинг"}:
            await message.answer(
                resp.ok("Отдельный рейтинг убран. Оценка академика — в карточке и в составе.")
            )
            return

        if sub in {"student", "card", "кто"}:
            if access_level < AccessLevel.SUPERVISOR:
                await message.answer(resp.error("Карточку академика смотрит наставник или ЗГС."))
                return
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
                "/academy submit — список открытых заданий\n"
                "/academy submit <id> текст — сдать отчёт"
            )
        )
