"""Доступ спикера конгресса: setnick, kick и msg только в конференции (+ msg в ЛС)."""

from __future__ import annotations

import functools
from collections.abc import Awaitable, Callable
from typing import ParamSpec, TypeVar

from vkbottle.bot import Message

from database.models.user import AccessLevel
from database.repository.congress_repo import CongressRepository
from database.repository.forum_role_repo import ForumRoleRepository
from database.repository.user_repo import UserRepository
from middlewares.access import AccessChecker

P = ParamSpec("P")
R = TypeVar("R")


def requires_setnick(
    func: Callable[P, Awaitable[R]],
) -> Callable[P, Awaitable[R | None]]:
    """PGS глобально или спикер/вице в беседе конгресса."""

    @functools.wraps(func)
    async def wrapper(message: Message, *args: P.args, **kwargs: P.kwargs) -> R | None:
        user_id = message.from_id
        if not user_id or user_id <= 0:
            return None

        server_id = await AccessChecker.resolve_server_id(message.peer_id, user_id)

        if await CongressRepository.can_setnick_in_chat(
            message.peer_id, user_id, server_id
        ):
            kwargs["server_id"] = server_id
            kwargs["access_level"] = await AccessChecker.get_level(user_id, server_id)
            return await func(message, *args, **kwargs)

        if not await ForumRoleRepository.can_use_forum_bot(user_id):
            await message.answer(
                "⛔ У вас нет доступа к боту. Обратитесь к администратору."
            )
            return None

        level = await AccessChecker.get_level(user_id, server_id)
        if level < AccessLevel.PGS:
            await message.answer(
                f"⛔ Недостаточно прав.\n"
                f"Требуется: ПГС (ур. {AccessLevel.PGS})\n"
                f"Ваш уровень: {AccessChecker.level_name(level) if level else 'нет доступа'}"
            )
            return None

        kwargs["server_id"] = server_id
        kwargs["access_level"] = level
        return await func(message, *args, **kwargs)

    return wrapper


def requires_chat_kick(
    func: Callable[P, Awaitable[R]],
) -> Callable[P, Awaitable[R | None]]:
    """ЗГС глобально или спикер/вице — /kick только в беседе конгресса."""

    @functools.wraps(func)
    async def wrapper(message: Message, *args: P.args, **kwargs: P.kwargs) -> R | None:
        user_id = message.from_id
        if not user_id or user_id <= 0:
            return None

        server_id = await AccessChecker.resolve_server_id(message.peer_id, user_id)

        if await CongressRepository.can_kick_in_chat(
            message.peer_id, user_id, server_id
        ):
            kwargs["server_id"] = server_id
            kwargs["access_level"] = await AccessChecker.get_level(user_id, server_id)
            return await func(message, *args, **kwargs)

        if not await ForumRoleRepository.can_use_forum_bot(user_id):
            await message.answer(
                "⛔ У вас нет доступа к боту. Обратитесь к администратору."
            )
            return None

        level = await AccessChecker.get_level(user_id, server_id)
        if level < AccessLevel.ZGS:
            await message.answer(
                f"⛔ Недостаточно прав.\n"
                f"Требуется: ЗГС (ур. {AccessLevel.ZGS})\n"
                f"Ваш уровень: {AccessChecker.level_name(level) if level else 'нет доступа'}"
            )
            return None

        kwargs["server_id"] = server_id
        kwargs["access_level"] = level
        return await func(message, *args, **kwargs)

    return wrapper


def requires_msg(
    func: Callable[P, Awaitable[R]],
) -> Callable[P, Awaitable[R | None]]:
    """Супервайзер+ или спикер/вице — /msg только алиас конгресса (конфа или ЛС)."""

    @functools.wraps(func)
    async def wrapper(message: Message, *args: P.args, **kwargs: P.kwargs) -> R | None:
        user_id = message.from_id
        if not user_id or user_id <= 0:
            return None

        server_id = await AccessChecker.resolve_server_id(message.peer_id, user_id)

        if await CongressRepository.can_use_msg(
            message.peer_id, user_id, server_id
        ):
            kwargs["server_id"] = server_id
            kwargs["access_level"] = await AccessChecker.get_level(user_id, server_id)
            kwargs["msg_mode"] = "congress"
            return await func(message, *args, **kwargs)

        if not await ForumRoleRepository.can_use_forum_bot(user_id):
            await message.answer(
                "⛔ У вас нет доступа к боту. Обратитесь к администратору."
            )
            return None

        level = await AccessChecker.get_level(user_id, server_id)
        if level < AccessLevel.SUPERVISOR and not await UserRepository.is_developer(
            user_id
        ):
            await message.answer(
                f"⛔ Недостаточно прав.\n"
                f"Требуется: Супервайзер (ур. {AccessLevel.SUPERVISOR})\n"
                f"Ваш уровень: {AccessChecker.level_name(level) if level else 'нет доступа'}"
            )
            return None

        kwargs["server_id"] = server_id
        kwargs["access_level"] = level
        kwargs["msg_mode"] = "supervisor"
        return await func(message, *args, **kwargs)

    return wrapper
