"""Фоновый watchdog сессии форума: health → reconnect → опциональный syncjudges."""

from __future__ import annotations

import asyncio
import logging
import os
import time

from config.settings import DEFAULT_SERVER_ID
from services.forum_api import ForumService
from services.judge_forum_sync import sync_judge_list
from services.panel_client import report_bot_error

logger = logging.getLogger(__name__)

FORUM_WATCH_ENABLED = os.getenv("FORUM_WATCH_ENABLED", "1").strip().lower() not in (
    "0",
    "false",
    "no",
    "off",
)
FORUM_WATCH_INTERVAL_SEC = max(
    60,
    int(os.getenv("FORUM_WATCH_INTERVAL_SEC", "300") or "300"),
)
# 0 = не синкать список судей автоматически; иначе период в секундах (по умолч. 6ч).
FORUM_JUDGE_SYNC_INTERVAL_SEC = max(
    0,
    int(os.getenv("FORUM_JUDGE_SYNC_INTERVAL_SEC", "21600") or "21600"),
)
_ALERT_COOLDOWN_SEC = 3600.0


class ForumSessionWatcher:
    def __init__(self, forum: ForumService) -> None:
        self._forum = forum
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._last_alert_at = 0.0
        self._last_judge_sync_at = 0.0
        self._was_ok = True

    def start(self) -> None:
        if not FORUM_WATCH_ENABLED:
            logger.info("Forum session watcher disabled (FORUM_WATCH_ENABLED)")
            return
        if not self._forum.available:
            logger.info("Forum session watcher skipped (forum cookies not configured)")
            return
        if self._task and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._loop(), name="forum-session-watch")
        logger.info(
            "Forum session watcher started (health=%ss, judge_sync=%ss)",
            FORUM_WATCH_INTERVAL_SEC,
            FORUM_JUDGE_SYNC_INTERVAL_SEC or "off",
        )

    async def stop(self) -> None:
        self._stop.set()
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None

    async def _loop(self) -> None:
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=20)
            return
        except asyncio.TimeoutError:
            pass

        while not self._stop.is_set():
            try:
                await self._tick()
            except Exception as exc:
                logger.exception("forum session watch tick: %s", exc)
            try:
                await asyncio.wait_for(
                    self._stop.wait(),
                    timeout=FORUM_WATCH_INTERVAL_SEC,
                )
                return
            except asyncio.TimeoutError:
                pass

    async def _tick(self) -> None:
        report = await self._forum.check_health()
        if not report.ok:
            logger.warning(
                "Forum session unhealthy (logged_in=%s connected=%s): %s — reconnect",
                report.logged_in,
                report.connected,
                report.error or "unknown",
            )
            report = await self._forum.reconnect()

        if report.ok:
            if not self._was_ok:
                logger.info(
                    "Forum session restored%s",
                    f" as {report.username}" if report.username else "",
                )
            self._was_ok = True
        else:
            self._was_ok = False
            logger.error(
                "Forum session still down after reconnect: %s",
                report.error or "unknown",
            )
            await self._alert_once(report.error or "forum session invalid")

        if FORUM_JUDGE_SYNC_INTERVAL_SEC > 0 and report.ok:
            await self._maybe_sync_judges()

    async def _maybe_sync_judges(self) -> None:
        now = time.monotonic()
        if now - self._last_judge_sync_at < FORUM_JUDGE_SYNC_INTERVAL_SEC:
            return
        self._last_judge_sync_at = now
        server_id = DEFAULT_SERVER_ID
        try:
            ok, msg = await sync_judge_list(server_id, self._forum)
            if ok:
                logger.info("Forum watch: judge list synced server=%s", server_id)
            else:
                # disabled / no thread — не ошибка сессии
                logger.info("Forum watch: judge sync skipped server=%s: %s", server_id, msg)
        except Exception as exc:
            logger.exception("Forum watch: judge sync error: %s", exc)

    async def _alert_once(self, error: str) -> None:
        now = time.monotonic()
        if now - self._last_alert_at < _ALERT_COOLDOWN_SEC:
            return
        self._last_alert_at = now
        await report_bot_error(
            message=f"Forum session watchdog: {error}",
            level="error",
            url="forum-session-watch",
            context={"hint": "Обновите FORUM_XF_* cookies и /forumcheck reconnect"},
        )
