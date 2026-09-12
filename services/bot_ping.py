"""Сбор отчёта для команды /ping."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

import aiohttp
from tortoise import Tortoise
from vkbottle import API

from config.settings import PANEL_HEALTH_URL, VK_GROUP_ID
from services.http_session import get_http_session

logger = logging.getLogger(__name__)

_SLOW_MS = 1000


@dataclass(frozen=True)
class _Probe:
    ok: bool
    ms: int | None = None
    detail: str | None = None


def _panel_health_url() -> str:
    return (PANEL_HEALTH_URL or "").strip()


def format_uptime(seconds: int) -> str:
    """Формат как в /ping: «40ч, 33мин» / «5мин» / «12сек»."""
    if seconds < 0:
        seconds = 0
    if seconds < 60:
        return f"{seconds}сек"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}мин"
    hours = minutes // 60
    rest_min = minutes % 60
    if hours < 24:
        if rest_min:
            return f"{hours}ч, {rest_min}мин"
        return f"{hours}ч"
    days = hours // 24
    rest_h = hours % 24
    if rest_h and rest_min:
        return f"{days}д, {rest_h}ч, {rest_min}мин"
    if rest_h:
        return f"{days}д, {rest_h}ч"
    if rest_min:
        return f"{days}д, {rest_min}мин"
    return f"{days}д"


def _fmt_probe(label: str, probe: _Probe) -> str:
    if not probe.ok:
        suffix = probe.detail or "ошибка"
        return f"⏱️ {label}: ❌ {suffix}"
    if probe.ms is None:
        return f"⏱️ {label}: н/д"
    return f"⏱️ {label}: {probe.ms}мс"


async def _ping_vk(api: API) -> _Probe:
    t0 = time.perf_counter()
    try:
        params: dict[str, int | str] = {}
        if VK_GROUP_ID:
            params["group_id"] = VK_GROUP_ID
        await api.request("groups.getById", params)
        ms = int((time.perf_counter() - t0) * 1000)
        return _Probe(ok=True, ms=ms)
    except Exception as exc:
        logger.warning("ping vk failed: %s", exc)
        return _Probe(ok=False, detail="нет ответа")


async def _ping_db() -> _Probe:
    t0 = time.perf_counter()
    try:
        conn = Tortoise.get_connection("default")
        await conn.execute_query("SELECT 1")
        ms = int((time.perf_counter() - t0) * 1000)
        return _Probe(ok=True, ms=ms)
    except Exception as exc:
        logger.warning("ping db failed: %s", exc)
        return _Probe(ok=False, detail="нет ответа")


async def _ping_panel() -> _Probe:
    url = _panel_health_url()
    if not url:
        return _Probe(ok=True, ms=None)  # н/д — не ошибка конфигурации для сводки «проблемы»
    t0 = time.perf_counter()
    try:
        session = await get_http_session()
        timeout = aiohttp.ClientTimeout(total=4)
        async with session.get(url, timeout=timeout) as resp:
            ms = int((time.perf_counter() - t0) * 1000)
            if resp.status != 200:
                return _Probe(ok=False, ms=ms, detail=f"HTTP {resp.status}")
            return _Probe(ok=True, ms=ms)
    except Exception as exc:
        logger.warning("ping panel failed: %s", exc)
        return _Probe(ok=False, detail="нет ответа")


def _status_line(
    *,
    vk: _Probe,
    bot_ms: int,
    db: _Probe,
    panel: _Probe,
) -> str:
    failed: list[str] = []
    if not vk.ok:
        failed.append("VK API")
    if not db.ok:
        failed.append("БД")
    # Панель без URL (н/д) — не авария; явный fail — проблема
    if not panel.ok:
        failed.append("панель")

    if failed:
        return f"🩺 Есть проблемы: {', '.join(failed)}"

    slow: list[str] = []
    if vk.ok and vk.ms is not None and vk.ms >= _SLOW_MS:
        slow.append("VK API")
    if bot_ms >= _SLOW_MS:
        slow.append("бот")
    if db.ok and db.ms is not None and db.ms >= _SLOW_MS:
        slow.append("БД")
    if panel.ok and panel.ms is not None and panel.ms >= _SLOW_MS:
        slow.append("панель")

    if slow:
        return f"🩺 Есть задержки: {', '.join(slow)}"
    return "🩺 Все сервисы работают стабильно"


async def build_ping_report(api: API, *, started_at: float | None) -> str:
    """Собрать текст ответа /ping."""
    t0 = time.perf_counter()
    vk, db, panel = await asyncio.gather(_ping_vk(api), _ping_db(), _ping_panel())
    bot_ms = int((time.perf_counter() - t0) * 1000)

    if started_at is None:
        uptime = "н/д"
    else:
        uptime = format_uptime(int(time.monotonic() - started_at))

    lines = [
        _fmt_probe("Пинг VK API", vk),
        f"⏱️ Пинг бота: {bot_ms}мс",
        _fmt_probe("Пинг БД", db),
        _fmt_probe("Пинг панели", panel),
        f"⏳ Время работы: {uptime}",
        _status_line(vk=vk, bot_ms=bot_ms, db=db, panel=panel),
    ]
    return "\n".join(lines)
