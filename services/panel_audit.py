"""Проверка регистрации следящих на сайте (Discord для входа)."""

from __future__ import annotations

from database.models.user import AccessLevel, User, UserServerAccess
from database.repository.user_repo import UserRepository
from middlewares.access import AccessChecker
from services.display_name import DisplayNameService
from services.panel_client import get_discord_link, panel_api_configured
from services.panel_db import discord_links_for_vk_ids, panel_db_path


async def _resolve_discord_links(vk_ids: list[int]) -> dict[int, str]:
    if panel_db_path() or not panel_api_configured():
        return await discord_links_for_vk_ids(vk_ids)

    links: dict[int, str] = {}
    for vk_id in vk_ids:
        discord_id = await get_discord_link(vk_id)
        if discord_id:
            links[vk_id] = discord_id
    return links


def _staff_sort_key(item: tuple[User, int, UserServerAccess | None]) -> tuple[int, int]:
    user, level, _access = item
    return (-level, user.vk_id)


async def _collect_staff_rows(
    server_id: int,
    *,
    member_ids: set[int] | None = None,
) -> list[tuple[User, int, UserServerAccess | None]]:
    rows = await UserRepository.list_staff(server_id)
    result: list[tuple[User, int, UserServerAccess | None]] = []
    for user, level, access in rows:
        if member_ids is not None and user.vk_id not in member_ids:
            continue
        if not await UserRepository.can_use_portal(user.vk_id, server_id):
            continue
        result.append((user, level, access))
    return result


def split_vk_message(text: str, *, limit: int = 3900) -> list[str]:
    if len(text) <= limit:
        return [text]
    parts: list[str] = []
    current = ""
    for line in text.splitlines(keepends=True):
        if len(line) > limit:
            if current:
                parts.append(current.rstrip())
                current = ""
            for i in range(0, len(line), limit):
                parts.append(line[i : i + limit].rstrip())
            continue
        if len(current) + len(line) > limit:
            parts.append(current.rstrip())
            current = line
        else:
            current += line
    if current:
        parts.append(current.rstrip())
    return parts or [text[:limit]]


async def format_portal_registration_audit(
    server_id: int,
    api,
    *,
    chat_only: bool = False,
    member_ids: set[int] | None = None,
) -> str:
    rows = await _collect_staff_rows(server_id, member_ids=member_ids if chat_only else None)
    if not rows:
        if chat_only:
            return "📭 В этой беседе нет следящих с доступом к порталу."
        return "📭 Пользователей с доступом нет."

    rows.sort(key=_staff_sort_key)
    names = DisplayNameService(api, server_id)
    vk_ids = [user.vk_id for user, _, _ in rows]
    links = await _resolve_discord_links(vk_ids)

    missing: list[str] = []
    ready = 0
    for user, level, _access in rows:
        if await UserRepository.is_developer(user.vk_id):
            level = max(level, AccessLevel.DEVELOPER)
        if not await UserRepository.can_use_portal(user.vk_id, server_id):
            continue
        if links.get(user.vk_id):
            ready += 1
            continue
        link = await names.link_user(user.vk_id, server_id)
        title = AccessChecker.level_name(level)
        missing.append(f"• {link} — {title} ({level})")

    scope = "в беседе" if chat_only else "в реестре"
    header = f"🌐 Регистрация на сайте ({scope})"
    footer = "Привязка: /editmydiscord · запасной вход: /panel в ЛС бота"

    if not missing:
        return (
            f"{header}\n\n"
            f"✅ Все следящие ({ready}) могут войти через Discord.\n\n"
            f"{footer}"
        )

    lines = [
        header,
        "",
        f"❌ Не привязан Discord — не зарегистрированы на сайте ({len(missing)}):",
        *missing,
    ]
    if ready:
        lines.extend(["", f"✅ С Discord: {ready}"])
    lines.extend(["", footer])
    return "\n".join(lines)
