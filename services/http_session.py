"""Общий aiohttp.ClientSession для исходящих HTTP из бота."""

from __future__ import annotations

import asyncio
import logging

import aiohttp

logger = logging.getLogger(__name__)

_lock = asyncio.Lock()
_session: aiohttp.ClientSession | None = None


async def get_http_session() -> aiohttp.ClientSession:
    global _session
    if _session is not None and not _session.closed:
        return _session
    async with _lock:
        if _session is None or _session.closed:
            _session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30),
            )
            logger.debug("Shared aiohttp ClientSession created")
        return _session


async def close_http_session() -> None:
    global _session
    async with _lock:
        if _session is not None and not _session.closed:
            await _session.close()
            logger.debug("Shared aiohttp ClientSession closed")
        _session = None
