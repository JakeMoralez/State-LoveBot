"""Поля судьи для BBCode-шаблона (ник, должность, дата)."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone

from database.models.user import User, UserServerAccess
from services.panel_db import read_staff_note

logger = logging.getLogger(__name__)

MSK = timezone(timedelta(hours=3))


def escape_bbcode_text(value: str) -> str:
    return value.replace("[", "［").replace("]", "］")


def split_nickname_tags(raw: str) -> tuple[str, str, str]:
    """(полный ник, чистый ник без [тегов], строка тегов)."""
    text = (raw or "").strip()
    if not text:
        return "", "", ""

    tags: list[str] = []
    rest = text
    while True:
        match = re.match(r"^(\[[^\]]+\])\s*", rest)
        if not match:
            break
        tags.append(match.group(1))
        rest = rest[match.end() :].strip()

    clean = rest or text
    tag_str = " ".join(tags)
    return text, clean, tag_str


def _pick_position_from_sources(
    *,
    bot_note: str,
    panel: dict[str, str] | None,
) -> str:
    if bot_note:
        return bot_note
    if panel:
        for key in ("leader_position", "note", "leader_note"):
            value = (panel.get(key) or "").strip()
            if value:
                return value
    return ""


async def resolve_panel_staff_note(vk_id: int, server_id: int) -> dict[str, str] | None:
    return await read_staff_note(vk_id, server_id)


async def resolve_judge_position(user: User, server_id: int) -> str:
    bot_note = (user.note or "").strip()
    panel = await resolve_panel_staff_note(user.vk_id, server_id)
    return _pick_position_from_sources(bot_note=bot_note, panel=panel)


def judge_since(user: User) -> str:
    dt = user.last_used or user.added_at
    if not dt:
        return "—"
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(MSK).strftime("%d.%m.%Y")
    return str(dt)


async def resolve_nickname_raw(user: User, server_id: int) -> str:
    access = await UserServerAccess.get_or_none(user_id=user.vk_id, server_id=server_id)
    if access and (access.nickname or "").strip():
        return access.nickname.strip()
    if user.username and user.username.strip():
        return user.username.strip()
    return f"id{user.vk_id}"


def format_vk_forum_link(vk_id: int, label: str) -> str:
    """BBCode-ссылка на профиль VK для XenForo."""
    url = f"https://vk.ru/id{vk_id}"
    text = escape_bbcode_text(label.strip()) if label.strip() else f"id{vk_id}"
    return f"[url={url}]{text}[/url]"


async def build_judge_line_context(user: User, server_id: int) -> dict[str, str]:
    raw_nick = await resolve_nickname_raw(user, server_id)
    full_nick, clean_nick, tag_str = split_nickname_tags(raw_nick)
    position = await resolve_judge_position(user, server_id)
    since = judge_since(user)

    position_esc = escape_bbcode_text(position) if position else ""
    note_suffix = f" — {position_esc}" if position_esc else ""

    return {
        "{{nickname}}": escape_bbcode_text(full_nick),
        "{{clean_nickname}}": escape_bbcode_text(clean_nick),
        "{{tag}}": escape_bbcode_text(tag_str),
        "{{position}}": position_esc,
        "{{note}}": position_esc,
        "{{since}}": since,
        "{{note_suffix}}": note_suffix,
        "{{vk}}": format_vk_forum_link(user.vk_id, clean_nick or full_nick),
        "{{vk_url}}": f"https://vk.ru/id{user.vk_id}",
    }
