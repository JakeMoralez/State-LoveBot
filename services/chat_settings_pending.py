"""Сессия редактирования /chatsettings (выбор пункта по номеру)."""

from __future__ import annotations

import time
from dataclasses import dataclass

_TTL_SEC = 300
_sessions: dict[tuple[int, int], "ChatSettingsSession"] = {}


@dataclass
class ChatSettingsSession:
    peer_id: int
    user_id: int
    phase: str
    setting_key: str | None = None
    created_at: float = 0.0


def _cleanup() -> None:
    now = time.time()
    expired = [
        key
        for key, session in _sessions.items()
        if now - session.created_at > _TTL_SEC
    ]
    for key in expired:
        _sessions.pop(key, None)


def _key(peer_id: int, user_id: int) -> tuple[int, int]:
    return peer_id, user_id


def register_owner(peer_id: int, user_id: int) -> None:
    _cleanup()
    _sessions[_key(peer_id, user_id)] = ChatSettingsSession(
        peer_id=peer_id,
        user_id=user_id,
        phase="owner",
        created_at=time.time(),
    )


def start_pick_setting(peer_id: int, user_id: int) -> None:
    _cleanup()
    _sessions[_key(peer_id, user_id)] = ChatSettingsSession(
        peer_id=peer_id,
        user_id=user_id,
        phase="pick_setting",
        created_at=time.time(),
    )


def get(peer_id: int, user_id: int) -> ChatSettingsSession | None:
    _cleanup()
    return _sessions.get(_key(peer_id, user_id))


def clear(peer_id: int, user_id: int) -> None:
    _sessions.pop(_key(peer_id, user_id), None)


def is_callback_owner(actor_id: int, owner_id: object | None) -> bool:
    if owner_id is None:
        return False
    try:
        return int(owner_id) == actor_id
    except (TypeError, ValueError):
        return False
