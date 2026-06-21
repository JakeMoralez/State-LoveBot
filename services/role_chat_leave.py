"""Автоснятие ролей при выходе / кике из привязанных бесед."""

from __future__ import annotations

import logging

from vkbottle import API

from database.models.role_chat import ForumRoleKey
from database.repository.chat_repo import ChatRepository
from database.repository.congress_repo import CongressRepository
from database.repository.forum_role_repo import ForumRoleRepository
from middlewares.access import AccessChecker
from services.display_name import DisplayNameService

logger = logging.getLogger(__name__)

_ROLE_LABELS = {
    ForumRoleKey.JUDGE: "судьи",
    ForumRoleKey.ATTORNEY: "адвоката",
    ForumRoleKey.LEADER: "лидера",
    ForumRoleKey.ADMIN: "администратора",
}

_CONGRESS_LABELS = {
    "speaker": "спикера конгресса",
    "vice": "вице-спикера конгресса",
}


async def is_court_chat(peer_id: int, server_id: int | None = None) -> bool:
    role_chat = await ForumRoleRepository.get_role_chat_by_peer(peer_id)
    if role_chat and role_chat.role == ForumRoleKey.JUDGE:
        return True

    chat = await ChatRepository.get_by_peer_id(peer_id)
    if not chat or chat.alias != "court":
        return False
    if server_id is not None and chat.server_id != server_id:
        return False
    return True


async def revoke_judge_on_court_kick(
    peer_id: int,
    user_id: int,
    api: API,
    *,
    reason: str = "исключение из беседы court",
) -> str | None:
    if user_id <= 0 or peer_id < 2_000_000_000:
        return None

    chat = await ChatRepository.get_by_peer_id(peer_id)
    server_id = (
        chat.server_id
        if chat
        else await AccessChecker.resolve_server_id(peer_id, user_id)
    )
    if not await is_court_chat(peer_id, server_id):
        return None
    if not await ForumRoleRepository.clear_judge_role(user_id, server_id):
        return None

    link = await DisplayNameService(api, server_id).link_user(user_id, server_id)
    logger.info(
        "judge revoked on court kick: vk_id=%s peer=%s server=%s",
        user_id,
        peer_id,
        server_id,
    )
    return f"🔰 {link} — доступ судьи снят ({reason})."


async def handle_role_chat_leave(peer_id: int, user_id: int, api: API) -> str | None:
    if user_id <= 0 or peer_id < 2_000_000_000:
        return None

    role_chat = await ForumRoleRepository.get_role_chat_by_peer(peer_id)
    chat = await ChatRepository.get_by_peer_id(peer_id)
    if not role_chat and not await is_court_chat(peer_id):
        return None

    server_id = (
        role_chat.server_id
        if role_chat
        else chat.server_id
        if chat
        else await AccessChecker.resolve_server_id(peer_id, user_id)
    )
    names = DisplayNameService(api, server_id)
    link = await names.link_user(user_id, server_id)
    notices: list[str] = []

    if role_chat:
        congress_role = await CongressRepository.revoke_officer_on_leave(
            peer_id,
            user_id,
            server_id,
        )
        if congress_role:
            label = _CONGRESS_LABELS.get(congress_role, congress_role)
            notices.append(f"🏛 {link} — снят доступ {label} (выход из беседы).")
            logger.info(
                "congress %s revoked: vk_id=%s peer=%s server=%s",
                congress_role,
                user_id,
                peer_id,
                server_id,
            )

    if await is_court_chat(peer_id, server_id):
        if await ForumRoleRepository.clear_judge_role(user_id, server_id):
            notices.append(f"🔰 {link} — доступ судьи снят (выход из беседы court).")
            logger.info(
                "judge role revoked: vk_id=%s peer=%s server=%s",
                user_id,
                peer_id,
                server_id,
            )

    if role_chat:
        role = role_chat.role
        if role in _ROLE_LABELS and role != ForumRoleKey.JUDGE:
            if await ForumRoleRepository.revoke_role_on_leave(
                user_id,
                role,
                server_id,
            ):
                notices.append(
                    f"🔰 {link} — доступ {_ROLE_LABELS[role]} снят (выход из беседы)."
                )
                logger.info(
                    "%s role revoked: vk_id=%s peer=%s server=%s",
                    role,
                    user_id,
                    peer_id,
                    server_id,
                )

    if not notices:
        return None
    return "\n".join(notices)
