"""Одноразовые ссылки для входа на панель след. ЦА (HMAC, общий секрет с State-LoveAdmin)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time

PANEL_BASE_URL = os.getenv("PANEL_BASE_URL", "").rstrip("/")
SLED_BOT_SECRET = os.getenv("SLED_BOT_SECRET", "")
TOKEN_TTL_SEC = 300
RATE_LIMIT_SEC = 30

_last_request: dict[int, float] = {}


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _b64url_decode(raw: str) -> bytes:
    pad = "=" * (-len(raw) % 4)
    return base64.urlsafe_b64decode(raw + pad)


def panel_login_configured() -> bool:
    return bool(PANEL_BASE_URL and SLED_BOT_SECRET)


def check_rate_limit(vk_id: int) -> bool:
    """True если запрос разрешён."""
    now = time.time()
    last = _last_request.get(vk_id, 0.0)
    if now - last < RATE_LIMIT_SEC:
        return False
    _last_request[vk_id] = now
    return True


def create_login_token(vk_id: int) -> str:
    if not SLED_BOT_SECRET:
        raise RuntimeError("SLED_BOT_SECRET не настроен")
    payload = {
        "vk_id": int(vk_id),
        "exp": int(time.time()) + TOKEN_TTL_SEC,
        "jti": secrets.token_hex(16),
    }
    payload_b64 = _b64url_encode(
        json.dumps(payload, separators=(",", ":")).encode("utf-8"),
    )
    sig = hmac.new(
        SLED_BOT_SECRET.encode("utf-8"),
        payload_b64.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return f"{payload_b64}.{_b64url_encode(sig)}"


def build_login_url(vk_id: int) -> str:
    if not PANEL_BASE_URL:
        raise RuntimeError("PANEL_BASE_URL не настроен")
    token = create_login_token(vk_id)
    return f"{PANEL_BASE_URL}/api/auth/bot/callback?token={token}"
