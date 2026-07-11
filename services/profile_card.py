"""Карточка профиля пользователя (/me, /info)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone

from vkbottle import API

from database.repository.server_repo import ServerRepository
from database.repository.user_repo import UserRepository
from middlewares.access import AccessChecker
from services.display_name import DisplayNameService
from services.forum_account import forum_member_url, parse_forum_member_id
from services.panel_client import get_discord_profile
from services.server_display import format_server_label

MSK = timezone(timedelta(hours=3))


@dataclass(frozen=True)
class DiscordProfileView:
    discord_id: str | None
    discord_username: str | None
    discord_display_name: str | None


def format_appointed_date(dt: datetime | None) -> str | None:
    if not dt:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(MSK).strftime("%d.%m.%Y")


def days_on_post(dt: datetime | None) -> int | None:
    if not dt:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    appointed = dt.astimezone(MSK).date()
    today = datetime.now(MSK).date()
    return max(0, (today - appointed).days) + 1


def format_discord_line(profile: DiscordProfileView | None) -> str:
    if not profile or not profile.discord_id:
        return "💬 Discord: не указан"
    label = (profile.discord_username or profile.discord_display_name or "").strip()
    if label:
        return f"💬 Discord: {label} (ID: {profile.discord_id})"
    return f"💬 Discord: {profile.discord_id}"


async def format_profile_nick_link(vk_id: int, api: API, server_id: int) -> str:
    names = DisplayNameService(api, server_id)
    return await names.profile_card_nick(vk_id, server_id)


async def format_user_profile_card(
    vk_id: int,
    api: API,
    server_id: int,
) -> str:
    level = await UserRepository.get_access_level(vk_id, server_id)
    level_name = AccessChecker.level_name(level) if level else "нет доступа"

    nick_link = await format_profile_nick_link(vk_id, api, server_id)
    server = await ServerRepository.get_by_id(server_id)
    server_label = format_server_label(server, server_id)

    user = await UserRepository.get_by_vk_id(vk_id)
    forum_id = parse_forum_member_id(user.username if user else None)
    forum_url = forum_member_url(forum_id) if forum_id else ""

    discord_raw = await get_discord_profile(vk_id)
    discord_view = (
        DiscordProfileView(
            discord_id=discord_raw.discord_id,
            discord_username=discord_raw.discord_username,
            discord_display_name=discord_raw.discord_display_name,
        )
        if discord_raw
        else None
    )

    access = await UserRepository.get_server_access(vk_id, server_id)
    appointed = access.granted_at if access else None
    appointed_label = format_appointed_date(appointed)
    days = days_on_post(appointed)

    lines = [
        "📝 Основая информация о пользователе ⬇",
        "",
        f"👤 Ник пользователя: {nick_link}",
        f"🌐 Сервер: {server_label}",
        f"👥 Уровень доступа: {level_name}",
        "",
        format_discord_line(discord_view),
        f"🔗 Форум: {forum_url if forum_url else 'не указан'}",
        "",
    ]

    if appointed_label:
        lines.append(f"📅 Дата назначения: {appointed_label}")
        if days is not None:
            lines.append(f"🚀 Дней на посту: {days}")
    else:
        lines.append("📅 Дата назначения: не указана")
        lines.append("🚀 Дней на посту: —")

    return "\n".join(lines)
