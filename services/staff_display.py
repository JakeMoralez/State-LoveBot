"""Форматирование /staff: уровни и условные обозначения ролей."""

from __future__ import annotations

from database.models.user import User, UserServerAccess
from database.repository.user_repo import UserRepository
from middlewares.access import AccessChecker
from services.display_name import DisplayNameService


def format_access_badges(user: User, access: UserServerAccess | None) -> str:
    badges: list[str] = []
    if access and access.has_ca_access:
        badges.append("ЦА")
    if access and access.is_judge:
        badges.append("⚖")
    if access and access.is_congress_speaker:
        badges.append("🎙")
    if access and access.is_congress_vice:
        badges.append("🎖")
    if access and access.is_attorney:
        badges.append("📘")
    if access and access.is_leader:
        badges.append("🛡")
    if user.is_admin:
        badges.append("👑")
    if not badges:
        return ""
    return "".join(f"［{b}］" for b in badges)


def _format_staff_line(
    link: str,
    level: int,
    badges: str,
) -> str | None:
    level_part = ""
    if level >= 1:
        title = AccessChecker.level_name(level)
        level_part = f"{title} ({level})"

    if level_part and badges:
        return f"• {link} — {level_part} {badges}"
    if level_part:
        return f"• {link} — {level_part}"
    if badges:
        return f"• {link} — {badges}"
    return None


async def format_staff_list(server_id: int, api) -> str:
    rows = await UserRepository.list_staff(server_id)
    if not rows:
        return "📭 Пользователей с доступом нет."

    names = DisplayNameService(api, server_id)
    lines = [f"🔐 Доступы ({len(rows)}):"]
    for user, level, access in rows:
        if await UserRepository.is_developer(user.vk_id):
            level = max(level, 10)
        link = await names.link_user(user.vk_id, server_id)
        badges = format_access_badges(user, access)
        line = _format_staff_line(link, level, badges)
        if line:
            lines.append(line)

    return "\n".join(lines)
