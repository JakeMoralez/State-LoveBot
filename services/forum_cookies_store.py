"""Локальное хранение cookies форума и проверки браузера."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

from config.settings import BASE_DIR

logger = logging.getLogger(__name__)

FORUM_COOKIE_KEYS = ("xf_user", "xf_session", "xf_tfa_trust", "xf_csrf", "__Host-l7_clearance")
_STORE_PATH = BASE_DIR / "forum_cookies.json"


def _load_store() -> dict[str, Any]:
    if not _STORE_PATH.is_file():
        return {}
    try:
        raw: Any = json.loads(_STORE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("forum cookies store read: %s", exc)
        return {}
    return raw if isinstance(raw, dict) else {}


def load_persisted_cookies() -> dict[str, str]:
    raw = _load_store()
    return {
        key: str(raw[key])
        for key in FORUM_COOKIE_KEYS
        if raw.get(key)
    }


def load_persisted_user_agent() -> str | None:
    user_agent = _load_store().get("user_agent")
    if not isinstance(user_agent, str):
        return None
    return user_agent.strip() or None


def load_persisted_proxy() -> str | None:
    """Return None when unset, an empty string when explicitly disabled."""
    raw = _load_store()
    if "proxy" not in raw:
        return None
    proxy = raw.get("proxy")
    return str(proxy).strip() if proxy else ""


def save_persisted_cookies(
    cookies: dict[str, str],
    *,
    user_agent: str | None = None,
    proxy: str | None = None,
    persist_proxy: bool = False,
) -> None:
    payload = {
        key: cookies[key]
        for key in FORUM_COOKIE_KEYS
        if cookies.get(key)
    }
    if not payload.get("xf_user") or not payload.get("xf_session"):
        raise ValueError("Нужны xf_user и xf_session")
    existing_store = _load_store()
    existing_user_agent = load_persisted_user_agent()
    selected_user_agent = (
        existing_user_agent if user_agent is None else user_agent.strip() or None
    )
    if selected_user_agent:
        payload["user_agent"] = selected_user_agent
    if persist_proxy:
        # Empty string is a persisted instruction to disable the environment fallback.
        payload["proxy"] = proxy.strip() if proxy else ""
    elif "proxy" in existing_store:
        value = existing_store.get("proxy")
        payload["proxy"] = str(value).strip() if value else ""
    temporary_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=_STORE_PATH.parent,
            prefix=".forum_cookies-", suffix=".tmp", delete=False,
        ) as temporary:
            temporary_path = temporary.name
            json.dump(payload, temporary, ensure_ascii=False, indent=2)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, _STORE_PATH)
    finally:
        if temporary_path is not None and os.path.exists(temporary_path):
            os.unlink(temporary_path)


def clear_persisted_cookies() -> None:
    try:
        if _STORE_PATH.is_file():
            _STORE_PATH.unlink()
    except OSError as exc:
        logger.warning("forum cookies store clear: %s", exc)


def merge_cookie_sources(*sources: dict[str, str]) -> dict[str, str]:
    merged: dict[str, str] = {}
    for source in sources:
        for key in FORUM_COOKIE_KEYS:
            value = source.get(key)
            if value:
                merged[key] = str(value).strip().strip('"').strip("'")
    return merged
