"""Автоснятие роли судьи при выходе из привязанной беседы."""

from __future__ import annotations

import logging

from vkbottle import API

from database.models.role_chat import ForumRoleKey
from database.repository.forum_role_repo import ForumRoleRepository
from services.display_name import DisplayNameService

logger = logging.getLogger(__name__)


async def handle_role_chat_leave(peer_id: int, user_id: int, api: API) -> str | None:
    if user_id <= 0 or peer_id < 2_000_000_000:
        return None

    role = await ForumRoleRepository.find_role_by_peer(peer_id)
    if role != ForumRoleKey.JUDGE:
        return None

    if not await ForumRoleRepository.revoke_role_on_leave(user_id, role):
        return None

    names = DisplayNameService(api)
    link = await names.mention_user(user_id)

    logger.info("judge role revoked: vk_id=%s peer=%s", user_id, peer_id)
    return f"🔰 {link} — доступ судьи снят (выход из беседы)."
