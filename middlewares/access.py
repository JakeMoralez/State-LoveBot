"""Проверка уровней доступа (1–11) с учётом server_id."""

from __future__ import annotations

import functools
import inspect
import logging
from collections.abc import Awaitable, Callable
from typing import Any, ParamSpec, TypeVar

from vkbottle.bot import Message

from config.settings import DEFAULT_SERVER_ID, DEFAULT_SERVER_SLUG
from database.models.user import AccessLevel
from database.repository.chat_repo import ChatRepository
from database.repository.server_repo import ServerRepository
from database.repository.forum_role_repo import ForumRoleRepository
from database.repository.user_repo import UserRepository
from services.dev_server_context import get_dev_server_override

logger = logging.getLogger(__name__)

P = ParamSpec("P")
R = TypeVar("R")


def _filter_handler_kwargs(
    func: Callable[..., Any],
    kwargs: dict[str, Any],
) -> dict[str, Any]:
    """Передать в хендлер только kwargs, которые он объявил в сигнатуре."""
    sig = inspect.signature(func)
    if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()):
        return kwargs
    allowed = set(sig.parameters.keys()) - {"message"}
    return {k: v for k, v in kwargs.items() if k in allowed}


class AccessChecker:
    """Централизованная проверка прав с привязкой к серверу."""

    @staticmethod
    async def resolve_server_id(peer_id: int, user_id: int | None = None) -> int:
        if user_id and await UserRepository.is_developer(user_id):
            override = get_dev_server_override(user_id)
            if override is not None:
                return override

        chat = await ChatRepository.get_by_peer_id(peer_id)
        if chat:
            return chat.server_id

        server = await ServerRepository.get_by_id(DEFAULT_SERVER_ID)
        if server:
            return server.id

        server = await ServerRepository.get_by_slug(DEFAULT_SERVER_SLUG)
        if not server:
            raise RuntimeError("Сервер по умолчанию не настроен")
        return server.id

    @staticmethod
    async def get_level(user_id: int, server_id: int) -> int:
        return await UserRepository.get_access_level(user_id, server_id)

    @staticmethod
    async def check(user_id: int, server_id: int, min_level: int) -> bool:
        level = await AccessChecker.get_level(user_id, server_id)
        return level >= min_level

    @staticmethod
    def level_name(level: int) -> str:
        return AccessLevel.title(level)


def requires_level(
    min_level: int,
    *,
    server_scoped: bool = True,
    require_registered: bool = True,
) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R | None]]]:
    """Декоратор для хендлеров vkbottle: блокирует команду при недостаточном уровне."""

    def decorator(
        func: Callable[P, Awaitable[R]],
    ) -> Callable[P, Awaitable[R | None]]:
        @functools.wraps(func)
        async def wrapper(message: Message, *args: P.args, **kwargs: P.kwargs) -> R | None:
            user_id = message.from_id
            if user_id is None or user_id <= 0:
                return None

            if require_registered and not await ForumRoleRepository.can_use_forum_bot(
                user_id
            ):
                await message.answer(
                    "⛔ У вас нет доступа к боту. Обратитесь к администратору."
                )
                return None

            server_id = (
                await AccessChecker.resolve_server_id(message.peer_id, user_id)
                if server_scoped
                else (await ServerRepository.get_by_slug(DEFAULT_SERVER_SLUG)).id  # type: ignore[union-attr]
            )
            level = await AccessChecker.get_level(user_id, server_id)

            if level < min_level:
                required = AccessChecker.level_name(min_level)
                current = AccessChecker.level_name(level) if level else "нет доступа"
                await message.answer(
                    f"⛔ Недостаточно прав.\n"
                    f"Требуется: {required} (ур. {min_level})\n"
                    f"Ваш уровень: {current} (ур. {level})"
                )
                logger.warning(
                    "Отказ в доступе: user=%s server=%s need=%s have=%s cmd=%s",
                    user_id,
                    server_id,
                    min_level,
                    level,
                    func.__name__,
                )
                return None

            kwargs["server_id"] = server_id
            kwargs["access_level"] = level
            return await func(message, *args, **_filter_handler_kwargs(func, kwargs))

        return wrapper

    return decorator


def requires_public(
    func: Callable[P, Awaitable[R]],
) -> Callable[P, Awaitable[R | None]]:
    """Команда доступна всем в чате (без проверки уровня и регистрации)."""

    @functools.wraps(func)
    async def wrapper(message: Message, *args: P.args, **kwargs: P.kwargs) -> R | None:
        user_id = message.from_id
        if user_id is None or user_id <= 0:
            return None
        server_id = await AccessChecker.resolve_server_id(message.peer_id, user_id)
        kwargs["server_id"] = server_id
        kwargs["access_level"] = await AccessChecker.get_level(user_id, server_id)
        return await func(message, *args, **_filter_handler_kwargs(func, kwargs))

    return wrapper


def requires_zgs_or_gos(
    func: Callable[P, Awaitable[R]],
) -> Callable[P, Awaitable[R | None]]:
    """ЗГС (3) или ГС ГОС+ (6+)."""

    @functools.wraps(func)
    async def wrapper(message: Message, *args: P.args, **kwargs: P.kwargs) -> R | None:
        user_id = message.from_id
        if user_id is None or user_id <= 0:
            return None

        if not await ForumRoleRepository.can_use_forum_bot(user_id):
            await message.answer("⛔ У вас нет доступа к боту.")
            return None

        server_id = await AccessChecker.resolve_server_id(message.peer_id, user_id)
        level = await AccessChecker.get_level(user_id, server_id)
        allowed = level == AccessLevel.ZGS or level >= AccessLevel.GS_GOS
        if await UserRepository.is_developer(user_id):
            allowed = True

        if not allowed:
            await message.answer("⛔ Требуется ЗГС (3) или ГС ГОС+ (6+).")
            return None

        kwargs["server_id"] = server_id
        kwargs["access_level"] = level
        return await func(message, *args, **_filter_handler_kwargs(func, kwargs))

    return wrapper


def requires_developer(
    func: Callable[P, Awaitable[R]],
) -> Callable[P, Awaitable[R | None]]:
    @functools.wraps(func)
    async def wrapper(message: Message, *args: P.args, **kwargs: P.kwargs) -> R | None:
        user_id = message.from_id
        if not user_id or user_id <= 0:
            return None
        if not await UserRepository.is_developer(user_id):
            await message.answer("⛔ Только разработчик (ур. 10).")
            return None
        kwargs["server_id"] = await AccessChecker.resolve_server_id(
            message.peer_id,
            user_id,
        )
        kwargs["access_level"] = AccessLevel.DEVELOPER
        return await func(message, *args, **_filter_handler_kwargs(func, kwargs))

    return wrapper
