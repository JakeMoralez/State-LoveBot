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
    from database.models.chat_kind import ChatKind
    from services.chat_kind import resolve_kind

    kind, _sphere, kind_server = await resolve_kind(peer_id)
    if kind == ChatKind.JUDGE:
        if server_id is not None and kind_server is not None and int(kind_server) != int(server_id):
            return False
        return True

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
    from database.models.chat_kind import ChatKind
    from services.chat_kind import user_in_other_kind_chat

    if await user_in_other_kind_chat(api, user_id, server_id, ChatKind.JUDGE, peer_id):
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

    from services.chat_kind import handle_peer_leave

    notice = await handle_peer_leave(peer_id, user_id, api)
    if notice:
        return notice

    # Алиас court без нового типа — как раньше, но с проверкой других судейских.
    if not await is_court_chat(peer_id):
        return None
    server_id = await AccessChecker.resolve_server_id(peer_id, user_id)
    from database.models.chat_kind import ChatKind
    from services.chat_kind import user_in_other_kind_chat

    if await user_in_other_kind_chat(api, user_id, server_id, ChatKind.JUDGE, peer_id):
        return None
    if not await ForumRoleRepository.clear_judge_role(user_id, server_id):
        return None
    link = await DisplayNameService(api, server_id).link_user(user_id, server_id)
    return f"🔰 {link} — доступ судьи снят (выход из беседы)."
