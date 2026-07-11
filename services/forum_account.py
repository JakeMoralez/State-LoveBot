"""Форумный аккаунт (member id в users.username)."""

from __future__ import annotations

import re

FORUM_BASE = "https://forum.arizona-rp.com"
FORUM_MEMBER_URL_HINT = f"{FORUM_BASE}/members/655354/"

FORUM_MEMBER_URL_RE = re.compile(
    rf"^https?://forum\.arizona-rp\.com/members/(\d+)/?(?:[?#].*)?$",
    re.IGNORECASE,
)

FORUM_MEMBER_ID_RE = re.compile(r"^\d{4,12}$")


def normalize_forum_account(raw: str) -> str:
    cleaned = (raw or "").strip()
    if not cleaned:
        raise ValueError("Укажите ссылку на профиль форума")
    match = FORUM_MEMBER_URL_RE.match(cleaned)
    if match:
        return match.group(1)
    if FORUM_MEMBER_ID_RE.match(cleaned):
        return cleaned
    raise ValueError(f"Нужна ссылка вида {FORUM_MEMBER_URL_HINT}")


def forum_member_url(member_id: str | None) -> str:
    value = (member_id or "").strip()
    if not value:
        return ""
    return f"{FORUM_BASE}/members/{value}/"


def parse_forum_member_id(username: str | None) -> str | None:
    value = (username or "").strip()
    if not value or not FORUM_MEMBER_ID_RE.match(value):
        return None
    return value
