"""Служебные события беседы (raw longpoll): вход, выход, кик."""

from __future__ import annotations

import logging
from typing import Any, Literal

INVITE_ACTIONS = frozenset(
    {
        "chat_invite_user",
        "chat_invite_user_by_link",
        "chat_invite_user_by_message_request",
    }
)
LEAVE_ACTION = "chat_leave_user"
KICK_ACTION = "chat_kick_user"

ChatMemberEventKind = Literal["join", "leave_voluntary", "leave_kicked"]

logger = logging.getLogger(__name__)


def _resolve_member_id(
    action_type: str,
    *,
    member_id: int | None,
    from_id: int | None,
) -> int | None:
    if member_id and member_id > 0:
        return member_id
    if action_type in INVITE_ACTIONS and from_id and from_id > 0:
        return from_id
    return None


def _event_kind(
    action_type: str,
    *,
    member_id: int,
    from_id: int | None,
) -> ChatMemberEventKind | None:
    if action_type in INVITE_ACTIONS:
        return "join"
    if action_type == LEAVE_ACTION:
        return "leave_voluntary"
    if action_type == KICK_ACTION:
        # VK: добровольный выход = chat_kick_user, from_id == member_id.
        if from_id and from_id == member_id:
            return "leave_voluntary"
        return "leave_kicked"
    return None


def parse_chat_member_event(event: dict[str, Any]) -> dict[str, Any] | None:
    """Из message_new извлечь peer_id, участника и тип события."""
    message = (event.get("object") or {}).get("message") or {}
    peer_id = message.get("peer_id")
    if not peer_id or int(peer_id) < 2_000_000_000:
        return None

    action = message.get("action") or {}
    action_type = action.get("type")
    if not action_type:
        return None

    action_type = str(action_type)
    raw_member = action.get("member_id")
    member_id = int(raw_member) if raw_member else None
    from_id = message.get("from_id")
    from_id = int(from_id) if from_id else None

    resolved_member = _resolve_member_id(
        action_type,
        member_id=member_id,
        from_id=from_id,
    )
    if not resolved_member:
        return None

    kind = _event_kind(action_type, member_id=resolved_member, from_id=from_id)
    if not kind:
        return None

    actor_id = from_id if from_id and from_id > 0 else None

    return {
        "peer_id": int(peer_id),
        "action_type": action_type,
        "member_id": resolved_member,
        "actor_id": actor_id,
        "kind": kind,
    }
