"""TTL-сессии интерактивного /poolkick (выбор scope и доступов)."""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass

_TTL_SEC = 300
_pending: dict[str, "PendingPoolkickFlow"] = {}


@dataclass
class FoundPeerData:
    peer_id: int
    title: str
    sphere: str | None
    pool_id: int | None = None


@dataclass
class PendingPoolkickFlow:
    actor_id: int
    server_id: int
    target_vk_id: int
    peer_id: int
    reason: str | None
    source_sphere: str | None
    found: list[FoundPeerData]
    phase: str  # scope | access
    created_at: float
    pool_id: int | None = None


def _cleanup() -> None:
    now = time.time()
    expired = [k for k, v in _pending.items() if now - v.created_at > _TTL_SEC]
    for key in expired:
        _pending.pop(key, None)


def create_scope_session(
    *,
    actor_id: int,
    server_id: int,
    target_vk_id: int,
    peer_id: int,
    reason: str | None,
    source_sphere: str | None,
    found: list[FoundPeerData],
    pool_id: int | None = None,
) -> str:
    _cleanup()
    token = secrets.token_hex(8)
    _pending[token] = PendingPoolkickFlow(
        actor_id=actor_id,
        server_id=server_id,
        target_vk_id=target_vk_id,
        peer_id=peer_id,
        reason=reason,
        source_sphere=source_sphere,
        found=found,
        phase="scope",
        created_at=time.time(),
        pool_id=pool_id,
    )
    return token


def get(token: str, user_id: int) -> PendingPoolkickFlow | None:
    _cleanup()
    item = _pending.get(token)
    if not item or item.actor_id != user_id:
        return None
    if time.time() - item.created_at > _TTL_SEC:
        _pending.pop(token, None)
        return None
    return item


def pop(token: str, user_id: int) -> PendingPoolkickFlow | None:
    item = get(token, user_id)
    if not item:
        return None
    _pending.pop(token, None)
    return item


def set_phase(token: str, user_id: int, phase: str) -> PendingPoolkickFlow | None:
    item = get(token, user_id)
    if not item:
        return None
    item.phase = phase
    item.created_at = time.time()
    return item
