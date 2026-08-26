"""Ожидание выбора сферы после /poolkick."""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass

_TTL_SEC = 300
_pending: dict[str, "PendingPoolkickSphere"] = {}


@dataclass(frozen=True)
class PendingPoolkickSphere:
    actor_id: int
    server_id: int
    target_vk_id: int
    peer_id: int
    target_spheres: tuple[str, ...]
    chat_sphere: str | None
    created_at: float


def _cleanup() -> None:
    now = time.time()
    expired = [k for k, v in _pending.items() if now - v.created_at > _TTL_SEC]
    for key in expired:
        _pending.pop(key, None)


def create(
    *,
    actor_id: int,
    server_id: int,
    target_vk_id: int,
    peer_id: int,
    target_spheres: list[str],
    chat_sphere: str | None,
) -> str:
    _cleanup()
    token = secrets.token_hex(8)
    _pending[token] = PendingPoolkickSphere(
        actor_id=actor_id,
        server_id=server_id,
        target_vk_id=target_vk_id,
        peer_id=peer_id,
        target_spheres=tuple(target_spheres),
        chat_sphere=chat_sphere,
        created_at=time.time(),
    )
    return token


def pop(token: str, user_id: int) -> PendingPoolkickSphere | None:
    _cleanup()
    item = _pending.get(token)
    if not item or item.actor_id != user_id:
        return None
    if time.time() - item.created_at > _TTL_SEC:
        _pending.pop(token, None)
        return None
    _pending.pop(token, None)
    return item
