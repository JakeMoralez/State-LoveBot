"""Форматирование карточки темы форума (как legacy show_thread_info)."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

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
    created = _format_claim_date(info.get("created_date"))
    forum_name = (info.get("forum_name") or "Неизвестно").strip()
    is_closed = bool(info.get("is_closed", info.get("closed", False)))
    status = "закрыт" if is_closed else "открыт"
    body = _clean_body(str(info.get("body") or info.get("text_content") or ""))

    lines: list[str] = [title]
    if prefix:
        lines.append(prefix)
    lines.append("")
    lines.append(f"{author}  ·  {created}  ·  {status}")
    meta = forum_name
    if tid:
        meta = f"{meta}  ·  #{tid}"
    lines.append(meta)
    lines.append("")
    lines.append("— — —")
    lines.append("")

    if body:
        lines.append(body)
    else:
        lines.append("Содержание пустое.")

    text = "\n".join(lines)
    if len(text) <= VK_MESSAGE_LIMIT:
        return text

    # Обрезаем только тело, шапка остаётся целой
    header = "\n".join(lines[: lines.index("— — —") + 2])
    reserve = len(header) + 2
    max_body = max(120, VK_MESSAGE_LIMIT - reserve - 1)
    clipped = body[:max_body].rstrip() + "…"
    return f"{header}\n{clipped}"


def _format_claim_date(raw: Any) -> str:
    if raw is None:
        return "—"
    text = str(raw).strip()
    if not text:
        return "—"
    # YYYY-MM-DD → ДД.ММ.ГГГГ
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        try:
            y, m, d = text[:10].split("-")
            return f"{int(d):02d}.{int(m):02d}.{y}"
        except ValueError:
            pass
    return text


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
