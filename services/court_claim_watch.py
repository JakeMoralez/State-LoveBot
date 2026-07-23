"""Фоновый вотчер: новые темы в разделе судебных исков → беседа судей."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from vkbottle import API

from config.settings import FORUM_BASE_URL
from database.models.court_claim import CourtClaimSeen
from database.models.role_chat import ForumRoleKey
from database.repository.forum_role_repo import ForumRoleRepository
from database.repository.server_repo import ServerRepository
from services.forum_api import ForumService
from services.server_display import format_server_label

logger = logging.getLogger(__name__)

CLAIM_WATCH_ENABLED = os.getenv("CLAIM_WATCH_ENABLED", "1").strip().lower() not in (
    "0",
    "false",
    "no",
    "off",
)
CLAIM_WATCH_INTERVAL_SEC = max(
    30,
    int(os.getenv("CLAIM_WATCH_INTERVAL_SEC", "60") or "60"),
)


def _thread_url(thread_id: int) -> str:
    base = (FORUM_BASE_URL or "https://forum.arizona-rp.com").rstrip("/")
    return f"{base}/threads/{thread_id}/"


def _format_new_claim(row: dict[str, Any], *, server_label: str) -> str:
    title = (row.get("thread_title") or "Без названия").strip()
    author = (row.get("username_author") or "—").strip()
    prefix = (row.get("prefix") or "").strip()
    tid = int(row.get("thread_id") or 0)
    lines = [
        "📥 Новый иск",
        "",
        f"🖥 {server_label}",
        f"📌 {title}",
    ]
    if prefix:
        lines.append(f"🏷 {prefix}")
    lines.extend(
        [
            f"👤 Автор: {author}",
            f"🔗 {_thread_url(tid)}",
        ]
    )
    return "\n".join(lines)


class CourtClaimWatcher:
    def __init__(self, api: API, forum: ForumService) -> None:
        self._api = api
        self._forum = forum
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    def start(self) -> None:
        if not CLAIM_WATCH_ENABLED:
            logger.info("Court claim watcher disabled (CLAIM_WATCH_ENABLED)")
            return
        if self._task and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._loop(), name="court-claim-watch")
        logger.info(
            "Court claim watcher started (interval=%ss)",
            CLAIM_WATCH_INTERVAL_SEC,
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
        # Небольшая пауза после старта, чтобы форум/БД успели подняться
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=15)
            return
        except asyncio.TimeoutError:
            pass

        while not self._stop.is_set():
            try:
                await self._tick()
            except Exception as exc:
                logger.exception("court claim watch tick: %s", exc)
            try:
                await asyncio.wait_for(
                    self._stop.wait(),
                    timeout=CLAIM_WATCH_INTERVAL_SEC,
                )
                return
            except asyncio.TimeoutError:
                continue

    async def force_scan(self) -> str:
        """Принудительная проверка (для /claimwatch)."""
        if not CLAIM_WATCH_ENABLED:
            return "❌ Вотчер выключен (CLAIM_WATCH_ENABLED=0)."
        if not self._forum.backend or not self._forum.api:
            return "❌ Форум не подключён."

        servers = await ServerRepository.list_active()
        lines: list[str] = ["🔍 Claim watch — ручная проверка", ""]
        checked = 0
        total_new = 0
        total_seeded = 0
        skipped_no_chat = 0
        skipped_no_forum = 0

        for server in servers:
            forum_id = server.judge_forum_id
            if not forum_id:
                skipped_no_forum += 1
                continue
            peer_id = await ForumRoleRepository.get_role_chat(
                ForumRoleKey.JUDGE,
                server.id,
            )
            if not peer_id:
                skipped_no_chat += 1
                continue
            try:
                stats = await self._scan_server(
                    server_id=server.id,
                    judge_forum_id=int(forum_id),
                    peer_id=int(peer_id),
                )
            except Exception as exc:
                lines.append(f"⚠️ server={server.id}: {exc}")
                continue
            checked += 1
            total_new += stats["notified"]
            total_seeded += stats["seeded"]
            label = format_server_label(server, server.id)
            if stats["seeded"]:
                lines.append(
                    f"• {label}: seed {stats['seeded']} тем (уведомлений нет)"
                )
            else:
                lines.append(
                    f"• {label}: новых {stats['notified']}, "
                    f"уже видели {stats['known']}, на стр. {stats['scanned']}"
                )

        if not checked:
            lines.append("Нет серверов с разделом исков и /regcourt.")
        else:
            lines.extend(
                [
                    "",
                    f"Итого: серверов {checked}, новых уведомлений {total_new}"
                    + (f", seed {total_seeded}" if total_seeded else ""),
                ]
            )
        if skipped_no_forum or skipped_no_chat:
            lines.append(
                f"(пропущено: без forum={skipped_no_forum}, без беседы={skipped_no_chat})"
            )
        return "\n".join(lines)

    async def _tick(self) -> None:
        if not self._forum.backend or not self._forum.api:
            return

        servers = await ServerRepository.list_active()
        for server in servers:
            forum_id = server.judge_forum_id
            if not forum_id:
                continue
            peer_id = await ForumRoleRepository.get_role_chat(
                ForumRoleKey.JUDGE,
                server.id,
            )
            if not peer_id:
                continue
            try:
                await self._scan_server(
                    server_id=server.id,
                    judge_forum_id=int(forum_id),
                    peer_id=int(peer_id),
                )
            except Exception as exc:
                logger.warning(
                    "court claim watch server=%s forum=%s: %s",
                    server.id,
                    forum_id,
                    exc,
                )

    async def _scan_server(
        self,
        *,
        server_id: int,
        judge_forum_id: int,
        peer_id: int,
    ) -> dict[str, int]:
        category = await self._forum.api.get_category(judge_forum_id)
        if not category:
            return {"notified": 0, "seeded": 0, "known": 0, "scanned": 0}

        known_before = await CourtClaimSeen.filter(server_id=server_id).count()
        seed = known_before == 0

        # При первом запуске помечаем 1–2 страницы как уже виденные (без спама)
        pages = (1, 2) if seed else (1,)
        all_rows: list[dict[str, Any]] = []
        for page in pages:
            page_rows = await self._forum._fetch_category_page(category, page)
            if not page_rows:
                break
            all_rows.extend(page_rows)

        rows = self._forum._filter_court_threads(all_rows)
        server = await ServerRepository.get_by_id(server_id)
        server_label = format_server_label(server, server_id)

        notified = 0
        seeded = 0
        already = 0

        for row in rows:
            tid = int(row.get("thread_id") or 0)
            if tid <= 0:
                continue
            if await CourtClaimSeen.exists(thread_id=tid):
                already += 1
                continue

            if seed:
                await CourtClaimSeen.create(
                    thread_id=tid,
                    server_id=server_id,
                    notified=False,
                )
                seeded += 1
                continue

            text = _format_new_claim(row, server_label=server_label)
            sent = False
            try:
                await self._api.messages.send(
                    peer_id=peer_id,
                    message=text,
                    random_id=0,
                    disable_mentions=1,
                )
                sent = True
                notified += 1
                logger.info(
                    "new claim notify server=%s thread=%s peer=%s",
                    server_id,
                    tid,
                    peer_id,
                )
            except Exception as exc:
                logger.warning(
                    "new claim notify failed server=%s thread=%s: %s",
                    server_id,
                    tid,
                    exc,
                )

            await CourtClaimSeen.create(
                thread_id=tid,
                server_id=server_id,
                notified=sent,
            )

        if seed:
            logger.info(
                "court claim watch seeded server=%s (%s threads)",
                server_id,
                seeded,
            )

        return {
            "notified": notified,
            "seeded": seeded,
            "known": already,
            "scanned": len(rows),
        }
