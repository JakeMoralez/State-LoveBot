"""Форум Arizona RP — arizona_forum_async (как legacy/main.py)."""

from __future__ import annotations

import asyncio
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from config import FORUM_COOKIES, FORUM_USER_AGENT
from config.settings import BASE_DIR
from database.repository.server_repo import ServerRepository
from services.server_display import format_server_label
from services.forum_format import (
    case_word,
    format_created_date,
    format_duration_seconds,
    plural_cases,
)

logger = logging.getLogger(__name__)

_ARIZONA_IMPORT_ERROR: str | None = None

ArizonaAPI = None
_HAS_ARIZONA = False
try:
    from arizona_forum_async import ArizonaAPI

    _HAS_ARIZONA = True
except Exception as exc:
    _ARIZONA_IMPORT_ERROR = str(exc)
    logger.error("arizona_forum_async не загружен: %s", exc)

THREAD_URL_RE = re.compile(
    r"(?:https?://)?(?:[\w.-]+\.)?arizona-rp\.com/threads/(?:[^/\s?#]+\.)?(\d+)",
    re.IGNORECASE,
)


@dataclass
class ForumHealthReport:
    configured: bool
    connected: bool
    logged_in: bool
    username: str | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.configured and self.connected and self.logged_in


def format_forum_health(report: ForumHealthReport) -> str:
    lines = ["🔍 Проверка форума", ""]
    if not report.configured:
        lines.append("❌ Cookies: не заданы (FORUM_XF_USER / FORUM_XF_SESSION)")
    else:
        lines.append("✅ Cookies: заданы")
    if not report.connected:
        lines.append("❌ Подключение: нет")
    else:
        lines.append("✅ Подключение: активно")
    if report.logged_in and report.username:
        lines.append(f"✅ Сессия: {report.username}")
    elif report.logged_in:
        lines.append("✅ Сессия: авторизован")
    else:
        lines.append("❌ Сессия: протухла или недействительна")
    if report.error:
        lines.extend(["", f"ℹ️ {report.error}"])
    if not report.ok:
        lines.extend(
            [
                "",
                "Обновите cookies в .env и выполните /forumcheck reconnect",
                "или перезапустите бота (pm2 restart main).",
            ]
        )
    return "\n".join(lines)


class ForumService:
    def __init__(self) -> None:
        self._api: Any = None
        self._backend: str | None = None
        self._cookies_ok = self._cookies_configured()
        self._available = self._cookies_ok

    @staticmethod
    def _cookies_configured() -> bool:
        cookies = {k: v for k, v in FORUM_COOKIES.items() if v}
        return bool(cookies.get("xf_user") and cookies.get("xf_session"))

    @property
    def available(self) -> bool:
        return self._available

    @property
    def backend(self) -> str | None:
        return self._backend

    @property
    def api(self) -> Any:
        return self._api

    def _cookie_dict(self) -> dict[str, str]:
        return {k: str(v) for k, v in FORUM_COOKIES.items() if v}

    @staticmethod
    def _read_cookies_from_env() -> dict[str, str]:
        from dotenv import load_dotenv

        load_dotenv(BASE_DIR / ".env", override=True)
        raw = {
            "xf_user": os.getenv("FORUM_XF_USER"),
            "xf_session": os.getenv("FORUM_XF_SESSION"),
            "xf_tfa_trust": os.getenv("FORUM_XF_TFA_TRUST"),
        }
        return {k: str(v) for k, v in raw.items() if v}

    def _apply_env_cookies(self) -> bool:
        cookies = self._read_cookies_from_env()
        self._cookies_ok = bool(cookies.get("xf_user") and cookies.get("xf_session"))
        self._available = self._cookies_ok
        return self._cookies_ok

    async def connect(self) -> None:
        if not self._cookies_ok:
            raise RuntimeError("Заполните FORUM_XF_USER и FORUM_XF_SESSION в .env")

        if not _HAS_ARIZONA or ArizonaAPI is None:
            raise RuntimeError(
                "arizona_forum_async не установлен. "
                f"{_ARIZONA_IMPORT_ERROR or ''} "
                "Выполните: pip install -r requirements.txt"
            )

        cookies = self._cookie_dict()
        self._api = ArizonaAPI(FORUM_USER_AGENT or None, cookies)
        await self._api.connect()
        self._backend = "arizona"
        logger.info("✅ Подключение к форуму установлено (arizona_forum_async)")

    async def reconnect(self) -> ForumHealthReport:
        """Перечитать .env и переподключиться (после обновления cookies)."""
        await self.close()
        if not self._apply_env_cookies():
            return ForumHealthReport(
                configured=False,
                connected=False,
                logged_in=False,
                error="FORUM_XF_USER / FORUM_XF_SESSION не заданы в .env",
            )
        try:
            cookies = self._read_cookies_from_env()
            self._api = ArizonaAPI(FORUM_USER_AGENT or None, cookies)
            await self._api.connect()
            self._backend = "arizona"
            logger.info("✅ Форум: переподключение успешно")
        except Exception as exc:
            logger.error("Форум: переподключение не удалось: %s", exc)
            return ForumHealthReport(
                configured=True,
                connected=False,
                logged_in=False,
                error=str(exc),
            )
        return await self.check_health()

    async def check_health(self) -> ForumHealthReport:
        if not self._cookies_ok:
            return ForumHealthReport(
                configured=False,
                connected=False,
                logged_in=False,
                error="Cookies не заданы в .env",
            )
        if not self._api or not self._backend:
            return ForumHealthReport(
                configured=True,
                connected=False,
                logged_in=False,
                error="HTTP-сессия не открыта (ошибка при старте?)",
            )
        try:
            member = await self._api.get_current_member()
            if member:
                return ForumHealthReport(
                    configured=True,
                    connected=True,
                    logged_in=True,
                    username=getattr(member, "username", None),
                )
            return ForumHealthReport(
                configured=True,
                connected=True,
                logged_in=False,
                error="xf_session протух — обновите cookies",
            )
        except Exception as exc:
            return ForumHealthReport(
                configured=True,
                connected=True,
                logged_in=False,
                error=str(exc)[:200],
            )

    async def close(self) -> None:
        if self._api:
            try:
                await self._api.close()
            except Exception as exc:
                logger.warning("forum close: %s", exc)
            self._api = None
        self._backend = None

    @staticmethod
    def parse_thread_id(text: str) -> int | None:
        text = text.strip()
        match = THREAD_URL_RE.search(text)
        if match:
            return int(match.group(1))
        if text.isdigit():
            return int(text)
        m = re.search(r"threads/[^.]+\.(\d+)", text)
        if m:
            return int(m.group(1))
        m = re.search(r"/(\d+)/?$", text)
        if m:
            return int(m.group(1))
        return None

    @staticmethod
    def parse_forum_command(text: str, command: str) -> tuple[int | None, str | None]:
        lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
        if not lines:
            return None, None

        first = lines[0]
        prefix = command.lower()
        if first.lower().startswith(prefix):
            target_raw = first[len(prefix) :].strip()
        else:
            target_raw = first

        thread_id = ForumService.parse_thread_id(target_raw)
        body = "\n".join(lines[1:]).strip() if len(lines) > 1 else None
        return thread_id, body or None

    async def get_thread(self, thread_id: int) -> Any | None:
        if not self._api:
            return None
        try:
            return await self._api.get_thread(thread_id)
        except Exception as exc:
            logger.error("get_thread %s: %s", thread_id, exc)
            return None

    async def get_thread_info(self, thread_id: int) -> dict[str, Any] | None:
        thread = await self.get_thread(thread_id)
        if not thread:
            return None

        try:
            author = "Неизвестно"
            author_id = None
            if thread.creator:
                if getattr(thread.creator, "username", None):
                    author = thread.creator.username
                author_id = getattr(thread.creator, "id", None)

            node_id = None
            forum_name = "Неизвестно"
            try:
                category = await thread.get_category()
                if category:
                    node_id = getattr(category, "id", None)
                    if getattr(category, "title", None):
                        forum_name = category.title
            except Exception as exc:
                logger.warning("forum category thread=%s: %s", thread_id, exc)

            return {
                "title": thread.title,
                "author": author,
                "author_id": author_id,
                "created_date": format_created_date(getattr(thread, "create_date", None)),
                "forum_name": forum_name,
                "closed": thread.is_closed,
                "is_closed": thread.is_closed,
                "is_sticky": getattr(thread, "is_sticky", False),
                "category_id": node_id,
                "node_id": node_id,
                "thread_id": thread_id,
            }
        except Exception as exc:
            logger.error("get_thread_info %s: %s", thread_id, exc)
            return None

    async def set_thread_open(self, thread_id: int, opened: bool) -> tuple[bool, str]:
        thread = await self.get_thread(thread_id)
        if not thread:
            return False, "Тема не найдена."

        current_title = getattr(thread, "title", "")
        current_is_sticky = getattr(thread, "is_sticky", False)

        try:
            resp = await thread.edit_info(
                opened=opened,
                sticky=current_is_sticky,
                title=current_title,
            )
            if resp and resp.status == 200:
                return True, ""
            return False, "Ошибка при изменении статуса темы"
        except Exception as exc:
            logger.error("set_thread_open %s opened=%s: %s", thread_id, opened, exc)
            return False, f"Ошибка: {exc}"

    async def set_thread_sticky(self, thread_id: int, sticky: bool) -> tuple[bool, str]:
        thread = await self.get_thread(thread_id)
        if not thread:
            return False, "Тема не найдена."

        current_title = getattr(thread, "title", "")
        is_closed = getattr(thread, "is_closed", False)
        try:
            resp = await thread.edit_info(
                sticky=sticky,
                opened=not is_closed,
                title=current_title,
            )
            if resp and resp.status == 200:
                return True, ""
            return False, "Ошибка при изменении закрепления"
        except Exception as exc:
            logger.error("set_thread_sticky %s: %s", thread_id, exc)
            return False, f"Ошибка: {exc}"

    async def edit_thread_title(self, thread_id: int, new_title: str) -> tuple[bool, str]:
        new_title = new_title.strip()
        if not new_title:
            return False, "Укажите новый заголовок темы."

        thread = await self.get_thread(thread_id)
        if not thread:
            return False, "Тема не найдена."

        try:
            resp = await thread.edit_info(
                title=new_title,
                opened=not thread.is_closed,
                sticky=getattr(thread, "is_sticky", False),
            )
            if resp and resp.status == 200:
                return True, f"Заголовок темы обновлён: {new_title}"
            return False, f"Форум отклонил изменение (HTTP {getattr(resp, 'status', '?')})."
        except Exception as exc:
            logger.error("edit_thread_title %s: %s", thread_id, exc)
            return False, f"Ошибка: {exc}"

    @staticmethod
    def _is_under_review(prefix: str | None) -> bool:
        if not prefix:
            return False
        lowered = prefix.lower()
        return "рассмотр" in lowered or "ожидан" in lowered

    @staticmethod
    def _is_important_prefix(prefix: str | None) -> bool:
        if not prefix:
            return False
        return prefix.strip().lower().startswith("важно")

    @staticmethod
    def _filter_court_threads(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            row
            for row in rows
            if not ForumService._is_important_prefix(row.get("prefix"))
        ]

    async def _fetch_category_page(
        self,
        category: Any,
        page: int,
    ) -> list[dict[str, Any]]:
        try:
            rows = await category.get_thread_category_detail(page=page)
        except Exception as exc:
            logger.error("court stats page %s: %s", page, exc)
            return []
        if not rows:
            return []
        return list(rows)

    async def _collect_threads_by_pages(
        self,
        category: Any,
        pages: int,
    ) -> tuple[list[dict[str, Any]], int]:
        page_data = await asyncio.gather(
            *[
                self._fetch_category_page(category, p)
                for p in range(1, pages + 1)
            ],
            return_exceptions=True,
        )
        threads: list[dict[str, Any]] = []
        pages_scanned = 0
        for page, rows in enumerate(page_data, start=1):
            if isinstance(rows, Exception):
                logger.error("court stats page %s: %s", page, rows)
                continue
            if not rows:
                continue
            pages_scanned += 1
            threads.extend(rows)
        return threads, pages_scanned

    async def _collect_threads_by_days(
        self,
        category: Any,
        days: int,
    ) -> tuple[list[dict[str, Any]], int]:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).timestamp()
        threads: list[dict[str, Any]] = []
        pages_scanned = 0
        empty_streak = 0

        for page in range(1, 81):
            rows = await self._fetch_category_page(category, page)
            if not rows:
                break

            pages_scanned += 1
            matched = [
                row
                for row in rows
                if row.get("created_date") is not None
                and row["created_date"] >= cutoff
            ]
            threads.extend(matched)

            if matched:
                empty_streak = 0
            else:
                empty_streak += 1
                if empty_streak >= 2:
                    break

        return threads, pages_scanned

    async def _resolve_closer_name(self, row: dict[str, Any]) -> str:
        closer = (row.get("username_last_message") or "").strip()
        if closer:
            return closer

        thread_id = row.get("thread_id")
        if not thread_id:
            return "Неизвестно"

        try:
            thread = await self._api.get_thread(int(thread_id))
            if not thread:
                return "Неизвестно"
            post_ids = await thread.get_posts()
            if not post_ids:
                return "Неизвестно"
            last_post = await self._api.get_post(post_ids[-1])
            creator = getattr(last_post, "creator", None)
            if creator and getattr(creator, "username", None):
                return creator.username
        except Exception as exc:
            logger.warning("court stats closer thread=%s: %s", thread_id, exc)
        return "Неизвестно"

    async def get_court_stats(
        self,
        *,
        server_id: int,
        judge_forum_id: int,
        pages: int | None = None,
        days: int | None = None,
    ) -> str:
        """Статистика исков/жалоб в разделе судебных исков сервера."""
        if not self._api:
            return "❌ Форум не подключён."

        category = await self._api.get_category(judge_forum_id)
        if not category:
            return "❌ Раздел судебных исков не найден"

        category_title = getattr(category, "title", "Судебные иски")

        if days is not None:
            days = max(1, min(days, 365))
            threads, pages_scanned = await self._collect_threads_by_days(category, days)
            period_label = f"за {days} дней"
            empty_hint = "📭 За указанный период нет тем"
        else:
            pages = max(1, min(pages or 1, 20))
            threads, pages_scanned = await self._collect_threads_by_pages(
                category, pages
            )
            period_label = ""
            empty_hint = "📭 На просканированных страницах нет тем"

        threads = self._filter_court_threads(threads)
        total_threads = len(threads)
        if total_threads == 0:
            return empty_hint

        pinned_count = sum(1 for row in threads if row.get("is_pinned"))
        closed_count = sum(1 for row in threads if row.get("is_closed"))
        open_count = total_threads - closed_count
        review_count = sum(
            1
            for row in threads
            if not row.get("is_closed")
            and self._is_under_review(row.get("prefix"))
        )

        close_durations: list[float] = []
        closed_by_stats: dict[str, int] = {}
        unknown_closers: list[dict[str, Any]] = []

        for row in threads:
            if not row.get("is_closed"):
                continue

            created = row.get("created_date")
            closed_at = row.get("last_message_date")
            if created and closed_at and closed_at >= created:
                close_durations.append(float(closed_at - created))

            closer = (row.get("username_last_message") or "").strip()
            if closer:
                closed_by_stats[closer] = closed_by_stats.get(closer, 0) + 1
            else:
                unknown_closers.append(row)

        if unknown_closers:
            sem = asyncio.Semaphore(8)

            async def _fill_closer(row: dict[str, Any]) -> tuple[str, int]:
                async with sem:
                    name = await self._resolve_closer_name(row)
                    return name, int(row.get("thread_id") or 0)

            resolved = await asyncio.gather(
                *[_fill_closer(row) for row in unknown_closers]
            )
            for name, _tid in resolved:
                closed_by_stats[name] = closed_by_stats.get(name, 0) + 1

        server = await ServerRepository.get_by_id(server_id)
        server_label = format_server_label(server, server_id)
        if period_label:
            header = (
                f"👻 Статистика {period_label} | {server_label} | "
                f"{category_title} 👻"
            )
        else:
            header = (
                f"👻 Статистика | {server_label} | {category_title} 👻"
            )

        if "жалоб" in category_title.lower():
            found_label = "жалоб"
        else:
            found_label = plural_cases(
                total_threads, one="иск", few="иска", many="исков"
            )
        found_line = f"📩 Найдено {found_label}: {total_threads}"
        if pages_scanned:
            found_line += f" ({pages_scanned} стр.)"

        avg_close = "—"
        if close_durations:
            avg_close = format_duration_seconds(
                sum(close_durations) / len(close_durations)
            )

        lines = [
            header,
            "",
            found_line,
            f"📁 На рассмотрении: {review_count}",
            f"📌 Закреплено: {pinned_count}",
            f"🔓 Открыто: {open_count}",
            f"🔐 Закрыто: {closed_count}",
            f"🔔 Ср. время закрытия: {avg_close}",
            "",
        ]

        if closed_count == 0:
            lines.append("📭 Нет закрытых тем за выбранный период")
            return "\n".join(lines)

        sorted_stats = sorted(closed_by_stats.items(), key=lambda x: x[1], reverse=True)
        num_emoji = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣"]
        for i, (closer, count) in enumerate(sorted_stats, 1):
            percentage = count / closed_count * 100
            word = case_word(category_title, count)
            if i <= 9:
                lines.append(
                    f"{num_emoji[i - 1]} {closer} закрыл(-а) {count} {word} "
                    f"[~{percentage:.0f}%]"
                )
            else:
                lines.append(
                    f"{i}. {closer} закрыл(-а) {count} {word} [~{percentage:.0f}%]"
                )
        return "\n".join(lines)

    async def is_logged_in(self) -> bool:
        if not self._api:
            return False
        try:
            member = await self._api.get_current_member()
            return member is not None
        except Exception:
            return False
