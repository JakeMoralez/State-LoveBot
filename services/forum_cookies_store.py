"""Локальное хранение cookies форума (xf_*), чтобы переживать ротацию сессии."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from config.settings import BASE_DIR

logger = logging.getLogger(__name__)

_COOKIE_KEYS = ("xf_user", "xf_session", "xf_tfa_trust")
_STORE_PATH = BASE_DIR / "forum_cookies.json"


def load_persisted_cookies() -> dict[str, str]:
    if not _STORE_PATH.is_file():
        return {}
    try:
        raw: Any = json.loads(_STORE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("forum cookies store read: %s", exc)
        return {}
    if not isinstance(raw, dict):
        return {}
    return {
        key: str(raw[key])
        for key in _COOKIE_KEYS
        if raw.get(key)
    }


def save_persisted_cookies(cookies: dict[str, str]) -> None:
    payload = {
        key: cookies[key]
        for key in _COOKIE_KEYS
        if cookies.get(key)
    }
    if not payload.get("xf_user") or not payload.get("xf_session"):
        return
    try:
        _STORE_PATH.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError as exc:
        logger.warning("forum cookies store write: %s", exc)


def merge_cookie_sources(*sources: dict[str, str]) -> dict[str, str]:
    merged: dict[str, str] = {}
    for source in sources:
        for key in _COOKIE_KEYS:
            value = source.get(key)
            if value:
                merged[key] = str(value)
    return merged
