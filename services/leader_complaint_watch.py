"""Фоновый вотчер: новые жалобы на лидеров (forum 3303) → беседа ruk_gos."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from vkbottle import API, Callback, Keyboard, KeyboardButtonColor, OpenLink

from config.settings import FORUM_BASE_URL, LEADER_COMPLAINT_FORUM_ID
from database.models.leader_complaint import LeaderComplaintSeen
from database.repository.chat_repo import ChatRepository
from database.repository.server_repo import ServerRepository
from services.forum_api import ForumService
from services.server_display import format_server_label

logger = logging.getLogger(__name__)

COMPLAINT_WATCH_ENABLED = os.getenv("COMPLAINT_WATCH_ENABLED", "1").strip().lower() not in (
    "0",
    "false",
    "no",
    "off",
)
COMPLAINT_WATCH_INTERVAL_SEC = max(
    30,
    int(os.getenv("COMPLAINT_WATCH_INTERVAL_SEC", "60") or "60"),
)
_RUK_GOS_ALIAS = "ruk_gos"


def _thread_url(thread_id: int) -> str:
    base = (FORUM_BASE_URL or "https://forum.arizona-rp.com").rstrip("/")
    return f"{base}/threads/{thread_id}/"


def _new_complaint_keyboard(thread_id: int, server_id: int) -> str:
    kb = Keyboard(inline=True)
    kb.add(OpenLink(link=_thread_url(thread_id), label="Открыть тему"))
    kb.add(
        Callback(
            "Информация",
            payload={
                "cmd": "complaint_info",
                "thread_id": thread_id,
                "server_id": server_id,
            },
        ),
        color=KeyboardButtonColor.PRIMARY,
    )
    return kb.get_json()


async def _format_new_complaint(
    api: API,
    row: dict[str, Any],
    *,
    server_id: int,
    server_label: str,
) -> str:
    title = (row.get("thread_title") or "Без названия").strip()
    author = (row.get("username_author") or "—").strip()
    prefix = (row.get("prefix") or "").strip()

    lines: list[str] = [
        "Новая жалоба на лидера",
        "",
        title,
    ]
    if prefix:
        lines.append(prefix)
    lines.append("")
    lines.append(f"{author}  ·  {server_label}")
    return "\n".join(lines)


async def _ruk_gos_targets() -> list[tuple[int, int]]:
    """(server_id, peer_id) для всех бесед с алиасом ruk_gos."""
    servers = await ServerRepository.list_active()
    out: list[tuple[int, int]] = []
    for server in servers:
        chat = await ChatRepository.get_by_alias(server.id, _RUK_GOS_ALIAS)
        if chat and chat.peer_id:
            out.append((int(server.id), int(chat.peer_id)))
    return out


class LeaderComplaintWatcher:
    def __init__(self, api: API, forum: ForumService) -> None:
        self._api = api
        self._forum = forum
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    def start(self) -> None:
        if not COMPLAINT_WATCH_ENABLED:
            logger.info("Leader complaint watcher disabled (COMPLAINT_WATCH_ENABLED)")
            return
        if not LEADER_COMPLAINT_FORUM_ID:
            logger.info("Leader complaint watcher skipped (LEADER_COMPLAINT_FORUM_ID=0)")
            return
        if self._task and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._loop(), name="leader-complaint-watch")
        logger.info(
            "Leader complaint watcher started (forum=%s interval=%ss)",
            LEADER_COMPLAINT_FORUM_ID,
            COMPLAINT_WATCH_INTERVAL_SEC,
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
                logger.exception("leader complaint watch tick: %s", exc)
            try:
                await asyncio.wait_for(
                    self._stop.wait(),
                    timeout=COMPLAINT_WATCH_INTERVAL_SEC,
                )
                return
            except asyncio.TimeoutError:
                continue

    async def force_scan(self) -> str:
        if not COMPLAINT_WATCH_ENABLED:
            return "❌ Вотчер выключен (COMPLAINT_WATCH_ENABLED=0)."
        if not LEADER_COMPLAINT_FORUM_ID:
            return "❌ LEADER_COMPLAINT_FORUM_ID не задан."
        if not self._forum.backend or not self._forum.api:
            return "❌ Форум не подключён."

        targets = await _ruk_gos_targets()
        if not targets:
            return "❌ Нет бесед с алиасом ruk_gos (/regchat … ruk_gos)."

        try:
            stats = await self._scan_forum(targets)
        except Exception as exc:
            return f"❌ Ошибка скана forum={LEADER_COMPLAINT_FORUM_ID}: {exc}"

        lines = [
            "🔍 Complaint watch — ручная проверка",
            "",
            f"Раздел: {LEADER_COMPLAINT_FORUM_ID}",
            f"Бесед ruk_gos: {len(targets)}",
        ]
        if stats["seeded"]:
            lines.append(f"Seed: {stats['seeded']} тем (уведомлений нет)")
        else:
            lines.append(
                f"Новых: {stats['notified']}, уже видели: {stats['known']}, "
                f"на стр.: {stats['scanned']}"
            )
        return "\n".join(lines)

    async def _tick(self) -> None:
        if not self._forum.backend or not self._forum.api:
            return
        if not LEADER_COMPLAINT_FORUM_ID:
            return
        targets = await _ruk_gos_targets()
        if not targets:
            return
        try:
            await self._scan_forum(targets)
        except Exception as exc:
            logger.warning(
                "leader complaint watch forum=%s: %s",
                LEADER_COMPLAINT_FORUM_ID,
                exc,
            )

    async def _scan_forum(
        self,
        targets: list[tuple[int, int]],
    ) -> dict[str, int]:
        category = await self._forum.api.get_category(LEADER_COMPLAINT_FORUM_ID)
        if not category:
            return {"notified": 0, "seeded": 0, "known": 0, "scanned": 0}

        known_before = await LeaderComplaintSeen.all().count()
        seed = known_before == 0

        pages = (1, 2) if seed else (1,)
        all_rows: list[dict[str, Any]] = []
        for page in pages:
            page_rows = await self._forum._fetch_category_page(category, page)
            if not page_rows:
                break
            all_rows.extend(page_rows)

        rows = self._forum._filter_court_threads(all_rows)

        notified = 0
        seeded = 0
        already = 0

        for row in rows:
            tid = int(row.get("thread_id") or 0)
            if tid <= 0:
                continue
            if await LeaderComplaintSeen.exists(thread_id=tid):
                already += 1
                continue

            # Для seed и уведомлений привязываем server_id первой ruk_gos-беседы
            anchor_server_id = targets[0][0]

            if seed:
                await LeaderComplaintSeen.create(
                    thread_id=tid,
                    server_id=anchor_server_id,
                    notified=False,
                )
                seeded += 1
                continue

            any_sent = False
            for server_id, peer_id in targets:
                server = await ServerRepository.get_by_id(server_id)
                server_label = format_server_label(server, server_id)
                text = await _format_new_complaint(
                    self._api,
                    row,
                    server_id=server_id,
                    server_label=server_label,
                )
                try:
                    await self._api.messages.send(
                        peer_id=peer_id,
                        message=text,
                        random_id=0,
                        disable_mentions=1,
                        keyboard=_new_complaint_keyboard(tid, server_id),
                    )
                    any_sent = True
                    logger.info(
                        "new leader complaint notify server=%s thread=%s peer=%s",
                        server_id,
                        tid,
                        peer_id,
                    )
                except Exception as exc:
                    logger.warning(
                        "leader complaint notify failed server=%s thread=%s: %s",
                        server_id,
                        tid,
                        exc,
                    )

            if any_sent:
                notified += 1

            await LeaderComplaintSeen.create(
                thread_id=tid,
                server_id=anchor_server_id,
                notified=any_sent,
            )

        if seed:
            logger.info(
                "leader complaint watch seeded (%s threads, forum=%s)",
                seeded,
                LEADER_COMPLAINT_FORUM_ID,
            )

        return {
            "notified": notified,
            "seeded": seeded,
            "known": already,
            "scanned": len(rows),
        }
