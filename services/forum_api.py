"""Форум Arizona RP — arizona_forum_async (как legacy/main.py)."""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from config import FORUM_COOKIES, FORUM_USER_AGENT
from config.settings import JUDGE_FORUM_ID, SERVER_NUMBER
from services.forum_format import format_created_date

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

    async def _collect_thread_ids_by_pages(self, category: Any, pages: int) -> list[int]:
        page_data = await asyncio.gather(
            *[category.get_threads(page=p) for p in range(1, pages + 1)],
            return_exceptions=True,
        )
        all_thread_ids: list[int] = []
        for page, threads_dict in enumerate(page_data, start=1):
            if isinstance(threads_dict, Exception):
                logger.error("court stats page %s: %s", page, threads_dict)
                continue
            if not threads_dict:
                continue
            all_thread_ids.extend(threads_dict.get("unpins") or [])
        return all_thread_ids

    async def _collect_thread_ids_by_days(self, category: Any, days: int) -> list[int]:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).timestamp()
        sem = asyncio.Semaphore(12)
        all_thread_ids: list[int] = []
        empty_streak = 0

        async def _in_range(thread_id: int) -> int | None:
            async with sem:
                try:
                    thread = await self._api.get_thread(thread_id)
                    if not thread:
                        return None
                    created = getattr(thread, "create_date", None)
                    if created is None or created >= cutoff:
                        return thread_id
                except Exception as exc:
                    logger.error("court stats thread %s: %s", thread_id, exc)
                return None

        for page in range(1, 81):
            try:
                threads_dict = await category.get_threads(page=page)
            except Exception as exc:
                logger.error("court stats page %s: %s", page, exc)
                break
            if not threads_dict:
                break

            unpins = threads_dict.get("unpins") or []
            if not unpins:
                empty_streak += 1
                if empty_streak >= 2:
                    break
                continue

            matched = [
                tid
                for tid in await asyncio.gather(*[_in_range(t) for t in unpins])
                if tid is not None
            ]
            all_thread_ids.extend(matched)
            if matched:
                empty_streak = 0
            else:
                empty_streak += 1
                if empty_streak >= 2:
                    break

        return all_thread_ids

    async def get_court_stats(
        self,
        *,
        pages: int | None = None,
        days: int | None = None,
    ) -> str:
        """Статистика закрытых исков в разделе судей (JUDGE_FORUM_ID)."""
        if not self._api:
            return "❌ Форум не подключён."

        category = await self._api.get_category(JUDGE_FORUM_ID)
        if not category:
            return "❌ Раздел судебных исков не найден"

        if days is not None:
            days = max(1, min(days, 365))
            all_thread_ids = await self._collect_thread_ids_by_days(category, days)
            scan_label = f"последние {days} дн."
            empty_hint = "📭 За указанный период нет тем"
        else:
            pages = max(1, min(pages or 1, 20))
            all_thread_ids = await self._collect_thread_ids_by_pages(category, pages)
            scan_label = "страницу" if pages == 1 else f"страниц: {pages}"
            empty_hint = "📭 На просканированных страницах нет тем"

        total_threads = len(all_thread_ids)
        if total_threads == 0:
            return empty_hint

        closed_by_stats: dict[str, int] = {}
        closed_count = 0
        open_count = 0
        sem = asyncio.Semaphore(12)

        async def _closer_name(thread: Any) -> str:
            try:
                post_ids = await thread.get_posts()
                if post_ids:
                    last_post = await self._api.get_post(post_ids[-1])
                    creator = getattr(last_post, "creator", None)
                    if creator and getattr(creator, "username", None):
                        return creator.username
            except Exception:
                pass
            return "Неизвестно"

        async def _analyze(thread_id: int) -> tuple[str, str | None] | None:
            async with sem:
                try:
                    thread = await self._api.get_thread(thread_id)
                    if not thread:
                        return None
                    if thread.is_closed:
                        return "closed", await _closer_name(thread)
                    return "open", None
                except Exception as exc:
                    logger.error("court stats thread %s: %s", thread_id, exc)
                    return None

        results = await asyncio.gather(*[_analyze(tid) for tid in all_thread_ids])
        for item in results:
            if not item:
                continue
            status, closer = item
            if status == "closed":
                closed_count += 1
                name = closer or "Неизвестно"
                closed_by_stats[name] = closed_by_stats.get(name, 0) + 1
            else:
                open_count += 1

        server_label = f"Arizona №{SERVER_NUMBER}" if SERVER_NUMBER else "Arizona"
        msg = (
            f"🔱 Статистика Судебных исков | {server_label} 🔱\n\n"
            f"📊 Просканировано {scan_label}\n"
            f"📩 Всего тем: {total_threads}\n"
            f"🔐 Закрыто: {closed_count}\n"
            f"🔓 Открыто: {open_count}\n\n"
        )

        if closed_count == 0:
            msg += "📭 Нет закрытых исков за выбранный период"
            return msg

        sorted_stats = sorted(closed_by_stats.items(), key=lambda x: x[1], reverse=True)
        num_emoji = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣"]
        for i, (closer, count) in enumerate(sorted_stats, 1):
            percentage = count / closed_count * 100
            if count % 10 == 1 and count % 100 != 11:
                word = "иск"
            elif 2 <= count % 10 <= 4 and (count % 100 < 10 or count % 100 >= 20):
                word = "иска"
            else:
                word = "исков"
            if i <= 9:
                msg += (
                    f"{num_emoji[i - 1]} {closer} закрыл(-а) {count} {word} "
                    f"[~{percentage:.0f}%]\n"
                )
            else:
                msg += f"{i}. {closer} закрыл(-а) {count} {word} [~{percentage:.0f}%]\n"
        return msg

    async def is_logged_in(self) -> bool:
        if not self._api:
            return False
        try:
            member = await self._api.get_current_member()
            return member is not None
        except Exception:
            return False
