"""Доступ к форумному функционалу — отдельно от уровней 1–10."""

from __future__ import annotations

import functools
import logging
from collections.abc import Awaitable, Callable
from typing import ParamSpec, TypeVar

from vkbottle.bot import Message

from config.settings import ATTORNEY_FORUM_ID, JUDGE_FORUM_ID, LEADER_ALLOWED_FORUMS
from database.models.user import AccessLevel
from database.repository.forum_role_repo import ForumRoleRepository
from database.repository.user_repo import UserRepository
from middlewares.access import AccessChecker

logger = logging.getLogger(__name__)

P = ParamSpec("P")
R = TypeVar("R")


class ForumAccessChecker:
    @staticmethod
    async def can_manage_court_roles(user_id: int, server_id: int) -> bool:
        """ЗГС (3+) и доступ ЦА для ур. 1–4; ур. 5+ — без флага ЦА."""
        if await UserRepository.is_developer(user_id):
            return True
        level = await UserRepository.get_access_level(user_id, server_id)
        if level < AccessLevel.ZGS:
            return False
        return await UserRepository.can_use_ca_scope(user_id, server_id)

    @staticmethod
    async def is_thread_allowed(user_id: int, forum_category_id: int, server_id: int) -> bool:
        level = await UserRepository.get_access_level(user_id, server_id)
        if level >= AccessLevel.ZGA:
            return True
        if await ForumRoleRepository.is_leader(user_id):
            return forum_category_id in LEADER_ALLOWED_FORUMS
        if await ForumRoleRepository.is_attorney(user_id):
            return forum_category_id == ATTORNEY_FORUM_ID
        if await ForumRoleRepository.is_judge(user_id):
            return forum_category_id == JUDGE_FORUM_ID
        return False


def requires_court_manager(
    func: Callable[P, Awaitable[R]],
) -> Callable[P, Awaitable[R | None]]:
    """ЗГС ЦА (ур. 3+) — для /addcourt, /regcourt и управления судьями."""

    @functools.wraps(func)
    async def wrapper(message: Message, *args: P.args, **kwargs: P.kwargs) -> R | None:
        user_id = message.from_id
        if not user_id or user_id <= 0:
            return None

        server_id = await AccessChecker.resolve_server_id(message.peer_id)
        if not await ForumAccessChecker.can_manage_court_roles(user_id, server_id):
            await message.answer(
                "⛔ Требуется ЗГС (3+) и доступ ЦА (ур. 1–4) или ур. 5+."
            )
            return None

        kwargs["server_id"] = server_id
        return await func(message, *args, **kwargs)

    return wrapper


# Алиас для обратной совместимости в импортах
requires_forum_manager = requires_court_manager


def requires_forum_user(
    func: Callable[P, Awaitable[R]],
) -> Callable[P, Awaitable[R | None]]:
    """Пользователь с форумной ролью или числовым уровнем доступа."""

    @functools.wraps(func)
    async def wrapper(message: Message, *args: P.args, **kwargs: P.kwargs) -> R | None:
        user_id = message.from_id
        if not user_id or user_id <= 0:
            return None

        if not await ForumRoleRepository.can_use_forum_bot(user_id):
            await message.answer("⛔ У вас нет доступа к боту. Обратитесь к администратору.")
            return None

        kwargs["server_id"] = await AccessChecker.resolve_server_id(message.peer_id)
        return await func(message, *args, **kwargs)

    return wrapper


def requires_judge(
    func: Callable[P, Awaitable[R]],
) -> Callable[P, Awaitable[R | None]]:
    @functools.wraps(func)
    async def wrapper(message: Message, *args: P.args, **kwargs: P.kwargs) -> R | None:
        user_id = message.from_id
        if not user_id or user_id <= 0:
            return None

        if not await ForumRoleRepository.is_judge(user_id):
            await message.answer("⛔ Команда доступна только судьям.")
            return None

        kwargs["server_id"] = await AccessChecker.resolve_server_id(message.peer_id)
        return await func(message, *args, **kwargs)

    return wrapper
