"""Request correlation id for LoveBot ↔ panel traces."""

from __future__ import annotations

import uuid
from contextvars import ContextVar

REQUEST_ID_HEADER = "X-Request-Id"

_request_id: ContextVar[str | None] = ContextVar("sled_request_id", default=None)


def new_request_id() -> str:
    return uuid.uuid4().hex[:16]


def get_request_id() -> str | None:
    return _request_id.get()


def set_request_id(value: str | None) -> None:
    _request_id.set((value or "").strip() or None)


def get_or_create_request_id() -> str:
    current = get_request_id()
    if current:
        return current
    rid = new_request_id()
    set_request_id(rid)
    return rid
