"""Форматирование карточки темы форума (как legacy show_thread_info)."""

from __future__ import annotations

from datetime import datetime
from typing import Any


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
