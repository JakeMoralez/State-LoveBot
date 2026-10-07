"""Форум Arizona RP — arizona_forum_async (как legacy/main.py)."""

from __future__ import annotations

import asyncio
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from config import FORUM_PROXY, FORUM_USER_AGENT
from config.settings import BASE_DIR
from database.repository.server_repo import ServerRepository
from services.forum_cookies_store import (
    FORUM_COOKIE_KEYS,
    load_persisted_cookies,
    load_persisted_proxy,
    load_persisted_user_agent,
    merge_cookie_sources,
    save_persisted_cookies,
)
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
    error_kind: str | None = None
    applied: bool | None = None

    @property
    def ok(self) -> bool:
        return self.configured and self.connected and self.logged_in and self.error is None


def format_forum_health(report: ForumHealthReport) -> str:
    lines = ["🔍 Проверка форума", ""]
    if not report.configured:
        lines.append(
            "❌ Cookies: не заданы "
            "(xf_user / xf_session в панели или FORUM_XF_USER / FORUM_XF_SESSION в .env)"
        )
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
                "Замените cookies в State Love Admin или .env и выполните /forumcheck reconnect",
                "или перезапустите бота (pm2 restart main).",
            ]
        )
    return "\n".join(lines)


class ForumService:
    def __init__(self) -> None:
        self._session_lock = asyncio.Lock()
        self._api: Any = None
        self._backend: str | None = None
        self._cookies_ok = self._cookies_configured()
        self._available = self._cookies_ok

    def _cookies_configured(self) -> bool:
        cookies = self._cookie_dict()
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
        persisted = load_persisted_cookies()
        if persisted.get("xf_user") and persisted.get("xf_session"):
            return persisted
        return merge_cookie_sources(self._read_cookies_from_env())

    @staticmethod
    def _user_agent() -> str | None:
        return load_persisted_user_agent() or FORUM_USER_AGENT or None

    @staticmethod
    def _proxy() -> str | None:
        persisted = load_persisted_proxy()
        if persisted is not None:
            return persisted or None
        return FORUM_PROXY or None

    @staticmethod
    def _session_cookies(api: Any, initial: dict[str, str]) -> dict[str, str]:
        session = getattr(api, "_session", None)
        if session is None or session.closed:
            return dict(initial)
        from yarl import URL

        # Only cookies actually sent to the forum, including scoped rotations.
        jar = session.cookie_jar.filter_cookies(URL("https://forum.arizona-rp.com/"))
        return {
            key: jar[key].value
            for key in FORUM_COOKIE_KEYS
            if key in jar and jar[key].value
        }

    async def _persist_session_cookies(self) -> None:
        if self._api is None or self._backend is None:
            return
        save_persisted_cookies(self._session_cookies(self._api, self._cookie_dict()))

    @staticmethod
    def _connection_error(exc: Exception) -> tuple[str, str]:
        from aiohttp import ClientResponseError
        from arizona_forum_async.exceptions import IncorrectLoginData

        cause: BaseException | None = exc
        seen: set[int] = set()
        while cause is not None and id(cause) not in seen:
            seen.add(id(cause))
            if isinstance(cause, IncorrectLoginData):
                return "authentication", "Форум отклонил авторизацию. Проверьте cookies и User-Agent из одной сессии браузера."
            if isinstance(cause, ClientResponseError):
                if cause.status in (401, 403):
                    return "authentication", f"Форум отклонил запрос (HTTP {cause.status}). Проверьте cookies и User-Agent; возможен отказ защиты форума."
                return "connection", f"Ошибка ответа форума (HTTP {cause.status})."
            cause = cause.__cause__ or cause.__context__
        # Do not expose arbitrary dependency exceptions: they may contain credentials.
        return "connection", "Не удалось подключиться к форуму или проверить аккаунт."

    @staticmethod
    async def _close_api(api: Any) -> None:
        try:
            await api.close()
        except Exception:
            logger.warning("Не удалось закрыть HTTP-сессию форума")

    async def _replace_connection(
        self,
        cookies: dict[str, str],
        user_agent: str | None,
        *,
        replacement: bool = False,
        proxy: str | None = None,
        persist_proxy: bool = False,
    ) -> ForumHealthReport:
        if not _HAS_ARIZONA or ArizonaAPI is None:
            return ForumHealthReport(True, False, False,
                error="Библиотека arizona_forum_async недоступна", error_kind="dependency")
        candidate = None
        accepted = False
        try:
            candidate = ArizonaAPI(user_agent, cookies, proxy=proxy)
            await candidate.connect()
            member = await candidate.get_current_member()
            if member is None:
                return ForumHealthReport(True, True, False,
                    error="Форум не подтвердил авторизацию аккаунта.", error_kind="authentication")
            rotated = self._session_cookies(candidate, cookies)
            if not rotated.get("xf_user") or not rotated.get("xf_session"):
                return ForumHealthReport(True, True, False,
                    error="После подключения отсутствуют cookies авторизации форума.", error_kind="authentication")
            try:
                save_persisted_cookies(
                    rotated,
                    user_agent=user_agent or "",
                    proxy=proxy,
                    persist_proxy=persist_proxy,
                )
            except OSError:
                return ForumHealthReport(True, True, True,
                    error="Не удалось сохранить cookies в файл на сервере бота.", error_kind="storage")
            previous = self._api
            self._api = candidate
            self._backend = "arizona"
            self._cookies_ok = True
            self._available = True
            accepted = True
            # The old jar must never overwrite the newly saved cookies.
            if previous is not None:
                await self._close_api(previous)
            return ForumHealthReport(True, True, True,
                username=getattr(member, "username", None), applied=True if replacement else None)
        except Exception as exc:
            kind, message = self._connection_error(exc)
            logger.warning("Форум: проверка подключения не удалась (%s)", kind)
            return ForumHealthReport(True, False, False, error=message, error_kind=kind)
        finally:
            if candidate is not None and not accepted:
                await self._close_api(candidate)

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

    async def connect(self) -> None:
        report = await self.reconnect()
        if not report.ok:
            raise RuntimeError(report.error or "Форум недоступен")

    async def apply_cookies(
        self,
        cookies: dict[str, str],
        user_agent: str | None = None,
    ) -> ForumHealthReport:
        """Проверить отдельную сессию и заменить текущую только после сохранения."""
        async with self._session_lock:
            cleaned = merge_cookie_sources(cookies)
            if not cleaned.get("xf_user") or not cleaned.get("xf_session"):
                return ForumHealthReport(False, False, False,
                    error="Нужны xf_user и xf_session. Новые cookies не применены.",
                    error_kind="validation", applied=False)
            if user_agent is not None and (
                len(user_agent) > 1024 or "\r" in user_agent or "\n" in user_agent
            ):
                return ForumHealthReport(True, False, False,
                    error="Некорректный User-Agent. Новые cookies не применены.",
                    error_kind="validation", applied=False)
            selected_agent = self._user_agent() if user_agent is None else user_agent.strip() or FORUM_USER_AGENT or None
            report = await self._replace_connection(
                cleaned,
                selected_agent,
                replacement=True,
                proxy=self._proxy(),
            )
            if not report.ok:
                report.applied = False
                report.error = f"{report.error} Новые cookies не применены; предыдущая конфигурация сохранена."
            return report

    async def apply_proxy(self, proxy: str | None = None, *, clear_proxy: bool = False) -> ForumHealthReport:
        """Validate and switch the proxy using the currently saved forum cookies."""
        if proxy is not None and (len(proxy) > 2048 or "\r" in proxy or "\n" in proxy):
            return ForumHealthReport(True, False, False,
                error="Некорректный адрес прокси. Настройка не применена.",
                error_kind="validation", applied=False)
        if proxy and clear_proxy:
            return ForumHealthReport(True, False, False,
                error="Нельзя одновременно задать и отключить прокси.",
                error_kind="validation", applied=False)
        if not proxy and not clear_proxy:
            return ForumHealthReport(True, False, False,
                error="Укажите адрес прокси или выберите его отключение.",
                error_kind="validation", applied=False)

        async with self._session_lock:
            cookies = self._cookie_dict()
            if not cookies.get("xf_user") or not cookies.get("xf_session"):
                return ForumHealthReport(False, False, False,
                    error="Сначала задайте xf_user и xf_session.",
                    error_kind="validation", applied=False)
            selected_proxy = proxy.strip() if proxy else None
            report = await self._replace_connection(
                cookies,
                self._user_agent(),
                replacement=True,
                proxy=selected_proxy,
                persist_proxy=True,
            )
            if not report.ok:
                report.applied = False
                report.error = f"{report.error} Настройка прокси не применена; предыдущая сессия сохранена."
            return report

    def cookies_status(self) -> dict[str, bool]:
        env = self._read_cookies_from_env()
        file_cookies = load_persisted_cookies()
        return {
            "env_xf_user": bool(env.get("xf_user")),
            "env_xf_session": bool(env.get("xf_session")),
            "env_xf_tfa_trust": bool(env.get("xf_tfa_trust")),
            "file_present": bool(file_cookies.get("xf_user") and file_cookies.get("xf_session")),
            "panel_user_agent": bool(load_persisted_user_agent()),
            "proxy_configured": bool(self._proxy()),
        }

    async def reconnect(self) -> ForumHealthReport:
        """Переподключение сериализовано с заменой cookies и проверкой сессии."""
        async with self._session_lock:
            cookies = self._cookie_dict()
            if not cookies.get("xf_user") or not cookies.get("xf_session"):
                return ForumHealthReport(False, False, False,
                    error="Задайте xf_user и xf_session в панели или .env", error_kind="validation")
            return await self._replace_connection(cookies, self._user_agent(), proxy=self._proxy())

    async def check_health(self) -> ForumHealthReport:
        async with self._session_lock:
            if not self._cookies_ok:
                return ForumHealthReport(False, False, False, error="Cookies не заданы")
            if not self._api or not self._backend:
                return ForumHealthReport(True, False, False, error="HTTP-сессия не открыта")
            try:
                member = await self._api.get_current_member()
                if member is None:
                    return ForumHealthReport(True, True, False,
                        error="Форум не подтвердил авторизацию аккаунта.", error_kind="authentication")
                try:
                    await self._persist_session_cookies()
                except OSError:
                    return ForumHealthReport(True, True, True,
                        error="Не удалось сохранить cookies в файл на сервере бота.", error_kind="storage")
                return ForumHealthReport(True, True, True, username=getattr(member, "username", None))
            except Exception as exc:
                kind, message = self._connection_error(exc)
                return ForumHealthReport(True, True, False, error=message, error_kind=kind)

    async def close(self) -> None:
        async with self._session_lock:
            if self._api is not None:
                await self._close_api(self._api)
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
        thread, _ = await self.get_thread_with_reconnect(thread_id)
        return thread

    async def get_thread_with_reconnect(
        self, thread_id: int
    ) -> tuple[Any | None, bool]:
        """Вернуть тему; при отсутствии — один раз переподключить сессию форума."""
        thread = await self._fetch_thread(thread_id)
        if thread is not None:
            return thread, False
        if not self._available:
            return None, False
        logger.info(
            "Forum thread %s not found — reconnecting session (forumcheck reconnect)...",
            thread_id,
        )
        report = await self.reconnect()
        if not report.ok:
            logger.warning(
                "Forum reconnect after missing thread %s failed: %s",
                thread_id,
                report.error,
            )
            return None, True
        thread = await self._fetch_thread(thread_id)
        return thread, True

    async def _fetch_thread(self, thread_id: int) -> Any | None:
        if not self._api:
            return None
        try:
            return await self._api.get_thread(thread_id)
        except Exception as exc:
            logger.error("get_thread %s: %s", thread_id, exc)
            return None

    async def _build_thread_info(self, thread: Any, thread_id: int) -> dict[str, Any] | None:
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
                "prefix": (getattr(thread, "prefix", None) or "").strip(),
                "body": (getattr(thread, "text_content", None) or "").strip(),
                "text_content": (getattr(thread, "text_content", None) or "").strip(),
            }
        except Exception as exc:
            logger.error("get_thread_info %s: %s", thread_id, exc)
            return None

    async def get_thread_info(self, thread_id: int) -> dict[str, Any] | None:
        info, _ = await self.get_thread_info_with_reconnect(thread_id)
        return info

    async def get_thread_info_with_reconnect(
        self, thread_id: int
    ) -> tuple[dict[str, Any] | None, bool]:
        thread, reconnected = await self.get_thread_with_reconnect(thread_id)
        if not thread:
            return None, reconnected
        info = await self._build_thread_info(thread, thread_id)
        return info, reconnected

    @staticmethod
    def thread_not_found_message(thread_id: int, *, reconnected: bool) -> str:
        base = f"Тема {thread_id} не найдена"
        if reconnected:
            return (
                f"{base}.\n"
                "Сессия форума обновлена автоматически — повтор не помог.\n"
                "Если ошибка остаётся, замените cookies в State Love Admin или .env "
                "и выполните /forumcheck reconnect."
            )
        return f"{base} или нет прав на просмотр."

    async def set_thread_open(self, thread_id: int, opened: bool) -> tuple[bool, str]:
        thread, reconnected = await self.get_thread_with_reconnect(thread_id)
        if not thread:
            return False, self.thread_not_found_message(thread_id, reconnected=reconnected)

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
        thread, reconnected = await self.get_thread_with_reconnect(thread_id)
        if not thread:
            return False, self.thread_not_found_message(thread_id, reconnected=reconnected)

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

    async def edit_thread_body(self, thread_id: int, body: str) -> tuple[bool, str]:
        body = body.strip()
        if not body:
            return False, "Пустое содержимое темы."

        thread, reconnected = await self.get_thread_with_reconnect(thread_id)
        if not thread:
            return False, self.thread_not_found_message(thread_id, reconnected=reconnected)

        post_id = getattr(thread, "thread_post_id", None)
        try:
            if post_id and self._api:
                logger.info(
                    "edit_thread_body: thread=%s post=%s len=%s",
                    thread_id,
                    post_id,
                    len(body),
                )
                resp = await self._api.edit_post(int(post_id), body)
            else:
                logger.warning(
                    "edit_thread_body: thread=%s fallback thread.edit (post_id missing)",
                    thread_id,
                )
                resp = await thread.edit(body)

            if not resp:
                return False, "Форум не вернул ответ."

            status = resp.status
            snippet = (await resp.text())[:800]
            logger.info(
                "edit_thread_body: thread=%s post=%s http=%s",
                thread_id,
                post_id,
                status,
            )
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("edit_thread_body response snippet: %s", snippet[:400])

            lowered = snippet.lower()
            if status not in (200, 303):
                return False, f"Форум отклонил изменение (HTTP {status})."
            if "you do not have permission" in lowered or "нет прав" in lowered:
                return False, "Нет прав редактировать первый пост (нужен модератор или автор темы)."
            if '"errors"' in snippet and "exception" not in lowered:
                return False, "Форум отклонил изменение (ошибка в ответе)."
            return True, "Содержимое темы обновлено."
        except Exception as exc:
            logger.error("edit_thread_body %s: %s", thread_id, exc)
            return False, f"Ошибка: {exc}"

    async def edit_thread_title(self, thread_id: int, new_title: str) -> tuple[bool, str]:
        new_title = new_title.strip()
        if not new_title:
            return False, "Укажите новый заголовок темы."

        thread, reconnected = await self.get_thread_with_reconnect(thread_id)
        if not thread:
            return False, self.thread_not_found_message(thread_id, reconnected=reconnected)

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
        threads: list[dict[str, Any]] = []
        pages_scanned = 0
        batch_size = 3

        for start in range(1, pages + 1, batch_size):
            chunk = range(start, min(start + batch_size, pages + 1))
            page_data = await asyncio.gather(
                *[self._fetch_category_page(category, p) for p in chunk],
                return_exceptions=True,
            )
            for page, rows in zip(chunk, page_data, strict=False):
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
        """Закрытые темы, у которых last_message_date (момент закрытия) за N дней."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).timestamp()
        threads: list[dict[str, Any]] = []
        pages_scanned = 0
        older_streak = 0

        for page in range(1, 81):
            rows = await self._fetch_category_page(category, page)
            if not rows:
                break

            pages_scanned += 1
            matched: list[dict[str, Any]] = []
            for row in rows:
                if not row.get("is_closed"):
                    continue
                closed_at = row.get("last_message_date")
                if closed_at is None:
                    continue
                if float(closed_at) >= cutoff:
                    matched.append(row)
            threads.extend(matched)

            # Останавливаемся только когда страница целиком старше окна
            # (не когда просто нет совпадений среди свежих тем).
            page_dates = [
                float(r["last_message_date"])
                for r in rows
                if r.get("last_message_date") is not None
            ]
            if matched:
                older_streak = 0
            elif page_dates and max(page_dates) < cutoff:
                older_streak += 1
                if older_streak >= 2:
                    break

        return threads, pages_scanned

    async def _collect_threads_by_range(
        self,
        category: Any,
        date_from: datetime,
        date_to: datetime,
    ) -> tuple[list[dict[str, Any]], int]:
        """Закрытые темы с last_message_date в [date_from, date_to] (UTC)."""
        if date_from.tzinfo is None:
            date_from = date_from.replace(tzinfo=timezone.utc)
        if date_to.tzinfo is None:
            date_to = date_to.replace(tzinfo=timezone.utc)
        start_ts = date_from.astimezone(timezone.utc).timestamp()
        end_ts = date_to.astimezone(timezone.utc).timestamp()
        if end_ts < start_ts:
            start_ts, end_ts = end_ts, start_ts

        threads: list[dict[str, Any]] = []
        pages_scanned = 0
        older_streak = 0

        for page in range(1, 81):
            rows = await self._fetch_category_page(category, page)
            if not rows:
                break

            pages_scanned += 1
            matched: list[dict[str, Any]] = []
            for row in rows:
                if not row.get("is_closed"):
                    continue
                closed_at = row.get("last_message_date")
                if closed_at is None:
                    continue
                if start_ts <= float(closed_at) <= end_ts:
                    matched.append(row)
            threads.extend(matched)

            page_dates = [
                float(r["last_message_date"])
                for r in rows
                if r.get("last_message_date") is not None
            ]
            if matched:
                older_streak = 0
            elif page_dates and max(page_dates) < start_ts:
                # Ушли глубже начала периода — дальше только старше
                older_streak += 1
                if older_streak >= 2:
                    break
            # Иначе страница ещё «новее» диапазона или внутри него без
            # нужных закрытий — продолжаем листать к нужным датам.

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
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        period_label: str | None = None,
    ) -> str:
        """Статистика исков/жалоб в разделе судебных исков сервера."""
        if not self._api:
            return "❌ Форум не подключён."

        category = await self._api.get_category(judge_forum_id)
        if not category:
            return "❌ Раздел судебных исков не найден"

        category_title = getattr(category, "title", "Судебные иски")

        if date_from is not None and date_to is not None:
            threads, pages_scanned = await self._collect_threads_by_range(
                category, date_from, date_to
            )
            period_label = period_label or "за выбранные даты"
            empty_hint = "📭 За указанные даты нет закрытых исков"
        elif days is not None:
            days = max(1, min(days, 365))
            threads, pages_scanned = await self._collect_threads_by_days(category, days)
            period_label = period_label or f"за {days} дней"
            empty_hint = "📭 За указанный период нет закрытых исков"
        else:
            pages = max(1, min(pages or 1, 20))
            threads, pages_scanned = await self._collect_threads_by_pages(
                category, pages
            )
            period_label = period_label or ""
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
            sem = asyncio.Semaphore(3)

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

    async def _resolve_closer_member_id(self, row: dict[str, Any]) -> str | None:
        """XF member id закрывшего (last post creator), если удаётся вытащить."""
        for key in ("user_id_last_message", "last_message_user_id", "closer_user_id"):
            raw = row.get(key)
            if raw is not None and str(raw).isdigit() and len(str(raw)) >= 4:
                return str(raw)

        thread_id = row.get("thread_id")
        if not thread_id or not self._api:
            return None
        try:
            thread = await self._api.get_thread(int(thread_id))
            if not thread:
                return None
            post_ids = await thread.get_posts()
            if not post_ids:
                return None
            last_post = await self._api.get_post(post_ids[-1])
            creator = getattr(last_post, "creator", None)
            if not creator:
                return None
            for attr in ("user_id", "id", "member_id"):
                val = getattr(creator, attr, None)
                if val is not None and str(val).isdigit() and len(str(val)) >= 4:
                    return str(val)
        except Exception as exc:
            logger.warning("claimfill closer member_id thread=%s: %s", thread_id, exc)
        return None

    async def fill_claim_closes(
        self,
        *,
        server_id: int,
        judge_forum_id: int,
        pages: int | None = None,
        days: int | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        period_label: str | None = None,
    ) -> str:
        """Дозаписать закрытые иски в БД по формунику (users.username)."""
        from database.models.user import User
        from database.repository.court_claim_repo import CourtClaimRepository
        from services.forum_account import parse_forum_member_id

        if not self._api:
            return "❌ Форум не подключён."

        category = await self._api.get_category(judge_forum_id)
        if not category:
            return "❌ Раздел судебных исков не найден"

        if date_from is not None and date_to is not None:
            threads, pages_scanned = await self._collect_threads_by_range(
                category, date_from, date_to
            )
            period = period_label or "даты"
        elif days is not None:
            days = max(1, min(days, 365))
            threads, pages_scanned = await self._collect_threads_by_days(category, days)
            period = period_label or f"за {days} дн."
        else:
            pages = max(1, min(pages or 1, 20))
            threads, pages_scanned = await self._collect_threads_by_pages(
                category, pages
            )
            period = period_label or f"{pages_scanned} стр."
        threads = self._filter_court_threads(threads)
        closed = [row for row in threads if row.get("is_closed")]
        if not closed:
            return f"📭 Закрытых тем нет ({period})."

        member_to_vk: dict[str, int] = {}
        for user in await User.all():
            mid = parse_forum_member_id(user.username)
            if mid and mid != str(user.vk_id):
                member_to_vk[mid] = user.vk_id

        added = 0
        skipped = 0
        unmatched = 0
        sem = asyncio.Semaphore(3)

        async def _process(row: dict[str, Any]) -> str:
            tid = int(row.get("thread_id") or 0)
            if not tid:
                return "skip"
            if await CourtClaimRepository.exists(tid):
                return "skip"

            async with sem:
                member_id = await self._resolve_closer_member_id(row)

            if not member_id or member_id not in member_to_vk:
                return "unmatched"

            closed_at = None
            ts = row.get("last_message_date")
            if ts:
                try:
                    closed_at = datetime.fromtimestamp(float(ts), tz=timezone.utc)
                except (TypeError, ValueError, OSError):
                    closed_at = None

            ok = await CourtClaimRepository.record_close_if_missing(
                tid,
                closed_by_vk_id=member_to_vk[member_id],
                server_id=server_id,
                forum_member_id=member_id,
                closed_at=closed_at,
            )
            return "added" if ok else "skip"

        results = await asyncio.gather(*[_process(row) for row in closed])
        for r in results:
            if r == "added":
                added += 1
            elif r == "skip":
                skipped += 1
            else:
                unmatched += 1

        return (
            f"✅ Claimfill ({period})\n"
            f"Закрытых тем: {len(closed)}\n"
            f"Добавлено: {added}\n"
            f"Уже в БД: {skipped}\n"
            f"Без матча по формунику: {unmatched}"
        )

    async def is_logged_in(self) -> bool:
        if not self._api:
            return False
        try:
            member = await self._api.get_current_member()
            return member is not None
        except Exception:
            return False
