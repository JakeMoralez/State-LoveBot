"""Автоснятие ролей при выходе из привязанных бесед."""

from __future__ import annotations

import logging

from vkbottle import API

from database.models.role_chat import ForumRoleKey
from database.repository.congress_repo import CongressRepository
from database.repository.forum_role_repo import ForumRoleRepository
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


async def handle_role_chat_leave(peer_id: int, user_id: int, api: API) -> str | None:
    if user_id <= 0 or peer_id < 2_000_000_000:
        return None

    names = DisplayNameService(api)
    link = await names.link_user(user_id)
    notices: list[str] = []

    congress_role = await CongressRepository.revoke_officer_on_leave(peer_id, user_id)
    if congress_role:
        label = _CONGRESS_LABELS.get(congress_role, congress_role)
        notices.append(f"🏛 {link} — снят доступ {label} (выход из беседы).")
        logger.info(
            "congress %s revoked: vk_id=%s peer=%s",
            congress_role,
            user_id,
            peer_id,
        )

    role = await ForumRoleRepository.find_role_by_peer(peer_id)
    if role and role in _ROLE_LABELS:
        if await ForumRoleRepository.revoke_role_on_leave(user_id, role):
            notices.append(
                f"🔰 {link} — доступ {_ROLE_LABELS[role]} снят (выход из беседы)."
            )
            logger.info("%s role revoked: vk_id=%s peer=%s", role, user_id, peer_id)

    if not notices:
        return None
    return "\n".join(notices)
