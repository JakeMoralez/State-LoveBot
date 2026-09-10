"""Ограничения для /internal/notify — без произвольного спама от имени бота."""

from __future__ import annotations

import time
from collections import defaultdict, deque

# Категории, которые панель реально шлёт (vk_notify / academy).
ALLOWED_NOTIFY_CATEGORIES = frozenset({"tasks", "assign", "system"})

MAX_NOTIFY_CHARS = 3500
# На одного получателя и глобально — защита при компрометации секрета.
_PER_VK_LIMIT = 8
_PER_VK_WINDOW_SEC = 60.0
_GLOBAL_LIMIT = 60
_GLOBAL_WINDOW_SEC = 60.0

_per_vk: dict[int, deque[float]] = defaultdict(deque)
_global: deque[float] = deque()


def normalize_notify_message(raw: object) -> tuple[str | None, str | None]:
    text = str(raw or "").strip()
    if not text:
        return None, "empty message"
    if len(text) > MAX_NOTIFY_CHARS:
        return None, f"message too long (max {MAX_NOTIFY_CHARS})"
    return text, None


def check_notify_rate_limit(vk_id: int) -> tuple[bool, str | None]:
    now = time.monotonic()
    while _global and now - _global[0] > _GLOBAL_WINDOW_SEC:
        _global.popleft()
    if len(_global) >= _GLOBAL_LIMIT:
        return False, "rate limit: too many notifies"

    q = _per_vk[vk_id]
    while q and now - q[0] > _PER_VK_WINDOW_SEC:
        q.popleft()
    if len(q) >= _PER_VK_LIMIT:
        return False, "rate limit: recipient"

    _global.append(now)
    q.append(now)
    return True, None
