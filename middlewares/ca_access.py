"""Проверка доступа ЦА для команд конгресса и суда (ур. 1–4)."""

from __future__ import annotations

import functools
from collections.abc import Awaitable, Callable
from typing import ParamSpec, TypeVar

from vkbottle.bot import Message

from database.models.user import AccessLevel
from database.repository.user_repo import UserRepository
from middlewares.access import AccessChecker

P = ParamSpec("P")
R = TypeVar("R")


def requires_ca_scope(
    func: Callable[P, Awaitable[R]],
) -> Callable[P, Awaitable[R | None]]:
    """Ур. 5+ — без ограничения; ур. 1–4 — нужен доступ ЦА (/setca или беседа след. ЦА)."""

    @functools.wraps(func)
    async def wrapper(message: Message, *args: P.args, **kwargs: P.kwargs) -> R | None:
        user_id = message.from_id
        if not user_id or user_id <= 0:
            return None

        server_id = kwargs.get("server_id") or await AccessChecker.resolve_server_id(
            message.peer_id,
            user_id,
        )
        if not await UserRepository.can_use_ca_scope(user_id, server_id):
            await message.answer(
                "⛔ Нужен доступ ЦА.\n"
                "Ур. 1–4: /setca или беседа след. ЦА.\n"
                "Ур. 5+ — без ограничения."
            )
            return None

        kwargs["server_id"] = server_id
        return await func(message, *args, **kwargs)

    return wrapper


async def can_review_court_forms(user_id: int, server_id: int) -> bool:
    """Модерация форм: доступ ЦА + ур. 2+ (Следящий)."""
    if await UserRepository.is_developer(user_id):
        return True
    level = await UserRepository.get_access_level(user_id, server_id)
    if level < AccessLevel.SUPERVISOR:
        return False
    return await UserRepository.can_use_ca_scope(user_id, server_id)


def requires_ca_form_reviewer(
    func: Callable[P, Awaitable[R]],
) -> Callable[P, Awaitable[R | None]]:
    """/forms, /acceptform, /rejectform — ЦА и мин. ур. 2 (Следящий)."""

    @functools.wraps(func)
    async def wrapper(message: Message, *args: P.args, **kwargs: P.kwargs) -> R | None:
        user_id = message.from_id
        if not user_id or user_id <= 0:
            return None

        server_id = kwargs.get("server_id") or await AccessChecker.resolve_server_id(
            message.peer_id,
            user_id,
        )
        if not await can_review_court_forms(user_id, server_id):
            await message.answer(
                "⛔ Модерация форм: нужен доступ ЦА и уровень 2+ (Следящий).\n"
                "ЦА: /setca или беседа след. ЦА.\n"
                "Ур. 5+ — доступ ЦА без отдельного флага."
            )
            return None

        kwargs["server_id"] = server_id
        return await func(message, *args, **kwargs)

    return wrapper
