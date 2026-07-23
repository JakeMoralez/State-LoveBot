"""Форматирование карточки темы форума (как legacy show_thread_info)."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from config.settings import FORUM_BASE_URL

VK_MESSAGE_LIMIT = 4090
_WS_RE = re.compile(r"[ \t]+\n")
_MULTI_NL_RE = re.compile(r"\n{3,}")


def format_thread_card(info: dict[str, Any]) -> str:
    is_closed = info.get("is_closed", info.get("closed", False))
    is_pinned = info.get("is_sticky", False)
    status_emoji = "🔒" if is_closed else "🔓"
    pin_emoji = "📌" if is_pinned else "📍"
    status_text = "Закрыта" if is_closed else "Открыта"

    author = info.get("author", "Неизвестно")
    author_id = info.get("author_id")
    author_line = f"👤 Автор: {author}"
    if author_id:
        author_line += f" (id{author_id})"

    return (
        f"{status_emoji} Тема: {info.get('title', 'Без названия')} {pin_emoji}\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"🆔 ID: {info.get('thread_id', '—')}\n"
        f"{status_emoji} Статус: {status_text}\n"
        f"{author_line}\n"
        f"📅 Создана: {info.get('created_date', 'Неизвестно')}\n"
        f"📂 Раздел: {info.get('forum_name', 'Неизвестно')}\n"
        f"━━━━━━━━━━━━━━━━"
    )


def _thread_url(thread_id: int) -> str:
    base = (FORUM_BASE_URL or "https://forum.arizona-rp.com").rstrip("/")
    return f"{base}/threads/{thread_id}/"


def _clean_body(text: str) -> str:
    cleaned = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    cleaned = _WS_RE.sub("\n", cleaned)
    cleaned = _MULTI_NL_RE.sub("\n\n", cleaned)
    return cleaned


def format_claim_detail(info: dict[str, Any]) -> str:
    """Карточка иска с содержимым первого поста (для кнопки «Информация»)."""
    tid = int(info.get("thread_id") or 0)
    title = (info.get("title") or "Без названия").strip()
    prefix = (info.get("prefix") or "").strip()
    author = (info.get("author") or "Неизвестно").strip()
    created = info.get("created_date") or "Неизвестно"
    forum_name = info.get("forum_name") or "Неизвестно"
    is_closed = bool(info.get("is_closed", info.get("closed", False)))
    status = "Закрыта" if is_closed else "Открыта"
    body = _clean_body(str(info.get("body") or info.get("text_content") or ""))

    header_lines = [
        f"📋 Иск: {title}",
    ]
    if prefix:
        header_lines.append(f"🏷 Префикс: {prefix}")
    header_lines.extend(
        [
            f"🆔 ID: {tid or '—'}",
            f"{'🔒' if is_closed else '🔓'} Статус: {status}",
            f"👤 Автор: {author}",
            f"📅 Создана: {created}",
            f"📂 Раздел: {forum_name}",
        ]
    )
    if tid:
        header_lines.append(f"🔗 {_thread_url(tid)}")
    header_lines.append("━━━━━━━━━━━━━━━━")
    header = "\n".join(header_lines)

    if not body:
        return f"{header}\n📄 Содержание: —"

    body_label = "📄 Содержание:\n"
    reserve = len(header) + 1 + len(body_label) + 40
    max_body = max(200, VK_MESSAGE_LIMIT - reserve)
    if len(body) > max_body:
        body = body[: max_body - 1].rstrip() + "…"
    return f"{header}\n{body_label}{body}"


def plural_cases(
    count: int,
    *,
    one: str,
    few: str,
    many: str,
) -> str:
    n = abs(count) % 100
    n1 = n % 10
    if 11 <= n <= 19:
        return many
    if n1 == 1:
        return one
    if 2 <= n1 <= 4:
        return few
    return many


def case_word(category_title: str, count: int) -> str:
    if "жалоб" in category_title.lower():
        return plural_cases(count, one="жалобу", few="жалобы", many="жалоб")
    return plural_cases(count, one="иск", few="иска", many="исков")


def format_duration_seconds(seconds: float) -> str:
    if seconds <= 0:
        return "—"
    total_minutes = int(seconds // 60)
    if total_minutes < 60:
        return f"{total_minutes} м."
    hours = total_minutes // 60
    minutes = total_minutes % 60
    if minutes:
        return f"{hours} ч. {minutes} м."
    return f"{hours} ч."


def format_created_date(timestamp: int | None) -> str:
    if not timestamp:
        return "Неизвестно"
    try:
        return datetime.fromtimestamp(int(timestamp)).strftime("%Y-%m-%d")
    except (ValueError, OSError, OverflowError):
        return str(timestamp)
