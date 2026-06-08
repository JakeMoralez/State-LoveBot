"""Ожидающие подтверждения оповещения /msg."""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass

_TTL_SEC = 300
_pending: dict[str, "PendingMsg"] = {}


@dataclass(frozen=True)
class PendingMsg:
    user_id: int
    server_id: int
    alias: str
    target_peer_id: int
    target_title: str | None
    text: str
    preview_body: str
    created_at: float


def _cleanup() -> None:
    now = time.time()
    expired = [k for k, v in _pending.items() if now - v.created_at > _TTL_SEC]
    for key in expired:
        _pending.pop(key, None)


def create(
    *,
    user_id: int,
    server_id: int,
    alias: str,
    target_peer_id: int,
    target_title: str | None,
    text: str,
    preview_body: str,
) -> str:
    _cleanup()
    token = secrets.token_hex(8)
    _pending[token] = PendingMsg(
        user_id=user_id,
        server_id=server_id,
        alias=alias,
        target_peer_id=target_peer_id,
        target_title=target_title,
        text=text,
        preview_body=preview_body,
        created_at=time.time(),
    )
    return token


def get(token: str, user_id: int) -> PendingMsg | None:
    _cleanup()
    item = _pending.get(token)
    if not item or item.user_id != user_id:
        return None
    if time.time() - item.created_at > _TTL_SEC:
        _pending.pop(token, None)
        return None
    return item


def pop(token: str, user_id: int) -> PendingMsg | None:
    item = get(token, user_id)
    if item:
        _pending.pop(token, None)
    return item
