"""Доступ ЦА / сфер: авто-выдача при входе только для уже зарегистрированных следящих."""

from __future__ import annotations

import logging

from vkbottle import API

from database.models.role_chat import ForumRoleKey
from database.models.user import AccessLevel
from database.repository.forum_role_repo import ForumRoleRepository
from database.repository.user_repo import UserRepository
from database.spheres import CENTRAL_APPARATUS
from middlewares.access import AccessChecker
from services.display_name import DisplayNameService
from services.panel_client import get_discord_link, sync_staff_spheres
from services.staff_nickname import (
    MINISTRY_NICK_TAGS,
    STRUCTURE_NICK_TAGS,
    strip_nickname_tags,
)

logger = logging.getLogger(__name__)

_SPHERE_SHORT: dict[str, str] = {
    **MINISTRY_NICK_TAGS,
    **STRUCTURE_NICK_TAGS,
    "server": "Сервер",
}


def sphere_access_label(sphere: str | None) -> str:
    if not sphere:
        return "ЦА"
    return _SPHERE_SHORT.get(sphere, sphere)


async def has_staff_registration_profile(vk_id: int, server_id: int) -> bool:
    """На сайте уже оформлен следящий: уровень + форум + discord + ник.

    Без этого вход в беседу сферы не выдаёт доступ (данных для регистрации в боте нет).
    """
    level = await UserRepository.get_access_level(vk_id, server_id)
    if level < AccessLevel.PGS:
        return False
    forum = await UserRepository.get_forum_member_id(vk_id)
    if not forum:
        return False
    discord = await get_discord_link(vk_id)
    if not discord:
        return False
    nick = await UserRepository.get_nickname(vk_id, server_id)
    if not strip_nickname_tags(nick or "").strip():
        return False
    return True


async def is_sled_ca_chat(peer_id: int) -> bool:
    from services.chat_kind import is_staff_ca, resolve_kind

    kind, sphere, _server = await resolve_kind(peer_id)
    if is_staff_ca(kind, sphere):
        return True
    chat = await ForumRoleRepository.get_role_chat_by_peer(peer_id)
    return chat is not None and chat.role == ForumRoleKey.SLED_CA


async def get_sled_ca_server_id(peer_id: int) -> int | None:
    from services.chat_kind import is_staff_ca, resolve_kind

    kind, sphere, server_id = await resolve_kind(peer_id)
    if is_staff_ca(kind, sphere) and server_id:
        return int(server_id)
    chat = await ForumRoleRepository.get_role_chat_by_peer(peer_id)
    if chat and chat.role == ForumRoleKey.SLED_CA:
        return chat.server_id
    return None


def format_staff_sphere_grant_message(
    link: str,
    *,
    level: int,
    sphere: str | None,
    granted_level: bool,
    granted_sphere: bool,
) -> str:
    level_name = AccessChecker.level_name(level) if level else AccessLevel.title(
        AccessLevel.PGS
    )
    sphere_label = sphere_access_label(sphere)
    if granted_level and granted_sphere:
        return (
            f"🎩 {link} получил уровень {level_name}［D:{level}］ "
            f"и доступ к {sphere_label}."
        )
    if granted_level:
        return f"🎩 {link} получил уровень {level_name}［D:{level}］."
    if granted_sphere:
        return f"🎩 {link} получил доступ к {sphere_label}."
    return f"🎩 {link} получил доступ к {sphere_label}."


async def handle_sled_ca_join(peer_id: int, user_id: int, api: API) -> str | None:
    """Устарело: логика в handle_peer_join / apply_join_effects."""
    del peer_id, user_id, api
    return None


async def handle_sled_ca_leave(peer_id: int, user_id: int, api: API) -> str | None:
    if user_id <= 0 or peer_id < 2_000_000_000:
        return None
    server_id = await get_sled_ca_server_id(peer_id)
    if not server_id:
        return None

    from database.models.chat_kind import ChatKind
    from services.chat_kind import user_in_other_kind_chat

    if await user_in_other_kind_chat(
        api, user_id, server_id, ChatKind.STAFF, peer_id, sphere=CENTRAL_APPARATUS
    ):
        return None

    changed, detail = await UserRepository.revoke_sled_ca_from_chat(
        user_id, server_id, peer_id
    )
    if not changed:
        return None

    if detail in ("ур. 1 и доступ ЦА", "ур. 1 и доступ к ЦА"):
        await sync_staff_spheres(user_id, grant_central_apparatus=False, server_id=server_id)

    link = await DisplayNameService(api, server_id).link_user(user_id, server_id)
    logger.info(
        "sled_ca leave revoked vk_id=%s peer=%s server=%s: %s",
        user_id,
        peer_id,
        server_id,
        detail,
    )
    return f"🔰 {link} — снят {detail} (выход из беседы следящих ЦА)."
