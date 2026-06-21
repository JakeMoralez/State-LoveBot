"""Автообновление темы на форуме со списком судей (BBCode)."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from database.models.judge_forum_list import JudgeForumListSettings
from database.models.role_chat import ForumRoleKey
from database.models.server import Server
from database.models.user import User, UserServerAccess
from database.repository.forum_role_repo import ForumRoleRepository
from services.forum_api import ForumService

logger = logging.getLogger(__name__)

MSK = timezone(timedelta(hours=3))

DEFAULT_BODY_TEMPLATE = """[center][size=5][b]Список судей[/b][/size][/center]
[i]Обновлено: {{updated_at}}[/i]

{{judges_block}}"""

DEFAULT_LINE_TEMPLATE = "[*]{{nickname}} — судья с {{since}}{{note_suffix}}"

DEFAULT_EMPTY_TEXT = "[i]Судей нет.[/i]"

JUDGE_LIST_FORUM_ID = 3758
JUDGE_LIST_FORUM_URL = f"https://forum.arizona-rp.com/forums/{JUDGE_LIST_FORUM_ID}/"

_SYNC_LOCKS: dict[int, asyncio.Lock] = {}
_PENDING: set[int] = set()


def escape_bbcode_text(value: str) -> str:
    return value.replace("[", "［").replace("]", "］")


def _judge_since(user: User) -> str:
    dt = user.last_used or user.added_at
    if not dt:
        return "—"
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(MSK).strftime("%d.%m.%Y")
    return str(dt)


async def _resolve_nickname(user: User, server_id: int) -> str:
    access = await UserServerAccess.get_or_none(user_id=user.vk_id, server_id=server_id)
    if access and (access.nickname or "").strip():
        return escape_bbcode_text(access.nickname.strip())
    if user.username and user.username.strip():
        return escape_bbcode_text(user.username.strip())
    return f"id{user.vk_id}"


def _format_updated_at(when: datetime | None = None) -> str:
    dt = when or datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(MSK).strftime("%d.%m.%Y %H:%M")


def _apply_line_template(
    template: str,
    *,
    nickname: str,
    since: str,
    note: str,
    index: int,
) -> str:
    note_suffix = f" — {escape_bbcode_text(note)}" if note.strip() else ""
    result = template
    replacements = {
        "{{nickname}}": nickname,
        "{{since}}": since,
        "{{note}}": escape_bbcode_text(note) if note.strip() else "",
        "{{note_suffix}}": note_suffix,
        "{{index}}": str(index),
    }
    for key, value in replacements.items():
        result = result.replace(key, value)
    return result


async def build_judges_block(
    server_id: int,
    *,
    line_template: str,
    empty_text: str,
) -> tuple[str, int]:
    users = await ForumRoleRepository.list_by_role(ForumRoleKey.JUDGE, server_id)
    if not users:
        return empty_text, 0

    lines: list[str] = []
    for index, user in enumerate(users, start=1):
        nickname = await _resolve_nickname(user, server_id)
        since = _judge_since(user)
        note = (user.note or "").strip()
        lines.append(
            _apply_line_template(
                line_template,
                nickname=nickname,
                since=since,
                note=note,
                index=index,
            )
        )
    return "[LIST]\n" + "\n".join(lines) + "\n[/LIST]", len(users)


async def render_judge_list_body(
    server_id: int,
    *,
    body_template: str | None = None,
    line_template: str | None = None,
    empty_text: str | None = None,
    updated_at: datetime | None = None,
) -> str:
    body = body_template or DEFAULT_BODY_TEMPLATE
    line = line_template or DEFAULT_LINE_TEMPLATE
    empty = empty_text or DEFAULT_EMPTY_TEXT

    judges_block, judges_count = await build_judges_block(
        server_id,
        line_template=line,
        empty_text=empty,
    )
    server = await Server.get_or_none(id=server_id)
    server_name = server.name if server else f"Сервер {server_id}"

    replacements = {
        "{{judges_block}}": judges_block,
        "{{judges_count}}": str(judges_count),
        "{{updated_at}}": _format_updated_at(updated_at),
        "{{server_name}}": escape_bbcode_text(server_name),
    }
    result = body
    for key, value in replacements.items():
        result = result.replace(key, value)
    return result


async def get_settings(server_id: int) -> JudgeForumListSettings:
    settings, _ = await JudgeForumListSettings.get_or_create(
        server_id=server_id,
        defaults={
            "body_template": DEFAULT_BODY_TEMPLATE,
            "line_template": DEFAULT_LINE_TEMPLATE,
            "empty_text": DEFAULT_EMPTY_TEXT,
        },
    )
    if not settings.body_template.strip():
        settings.body_template = DEFAULT_BODY_TEMPLATE
    if not settings.line_template.strip():
        settings.line_template = DEFAULT_LINE_TEMPLATE
    if not settings.empty_text.strip():
        settings.empty_text = DEFAULT_EMPTY_TEXT
    return settings


def _lock_for(server_id: int) -> asyncio.Lock:
    if server_id not in _SYNC_LOCKS:
        _SYNC_LOCKS[server_id] = asyncio.Lock()
    return _SYNC_LOCKS[server_id]


async def validate_judge_list_thread(
    server_id: int,
    thread_id: int,
    forum: ForumService | None = None,
) -> tuple[bool, str]:
    del server_id  # один раздел списка судей на все серверы
    required_forum_id = JUDGE_LIST_FORUM_ID

    svc = forum or ForumService()
    if not svc._api:
        try:
            if svc.available:
                await svc.connect()
        except Exception as exc:
            return False, f"Форум недоступен: {exc}"

    info = await svc.get_thread_info(thread_id)
    if not info:
        return False, "Тема не найдена на форуме."

    category_id = info.get("category_id") or info.get("node_id")
    if category_id != required_forum_id:
        forum_name = info.get("forum_name") or "?"
        return False, (
            f"Тема должна быть в разделе {JUDGE_LIST_FORUM_URL}, "
            f"а находится в forums/{category_id}/ ({forum_name})."
        )
    return True, ""


async def sync_judge_list(server_id: int, forum: ForumService | None = None) -> tuple[bool, str]:
    settings = await get_settings(server_id)
    if not settings.enabled:
        return False, "Синхронизация отключена"
    if not settings.thread_id:
        return False, "Не задан thread_id"

    svc = forum or ForumService()
    ok_forum, forum_err = await validate_judge_list_thread(
        server_id,
        settings.thread_id,
        svc,
    )
    if not ok_forum:
        logger.warning(
            "judge list sync skipped: server=%s thread=%s: %s",
            server_id,
            settings.thread_id,
            forum_err,
        )
        return False, forum_err

    body = await render_judge_list_body(
        server_id,
        body_template=settings.body_template,
        line_template=settings.line_template,
        empty_text=settings.empty_text,
    )

    ok, msg = await svc.edit_thread_body(settings.thread_id, body)
    if ok:
        logger.info("judge list synced: server=%s thread=%s", server_id, settings.thread_id)
    else:
        logger.warning(
            "judge list sync failed: server=%s thread=%s: %s",
            server_id,
            settings.thread_id,
            msg,
        )
    return ok, msg


async def _run_scheduled_sync(server_id: int) -> None:
    lock = _lock_for(server_id)
    async with lock:
        try:
            await sync_judge_list(server_id)
        except Exception as exc:
            logger.exception("judge list sync error server=%s: %s", server_id, exc)


def schedule_judge_list_sync(server_id: int) -> None:
    if server_id <= 0:
        return
    if server_id in _PENDING:
        return
    _PENDING.add(server_id)

    async def _task() -> None:
        try:
            await _run_scheduled_sync(server_id)
        finally:
            _PENDING.discard(server_id)

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_task())
    except RuntimeError:
        logger.debug("no event loop for judge list sync server=%s", server_id)
