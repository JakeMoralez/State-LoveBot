"""Единый стиль ответов бота: статус-глифы + человечные тексты.

Используйте эти хелперы вместо ручной склейки ``"❌ " + text`` — тогда сообщения
во всех модулях выглядят одинаково. Правила стиля: docs/voice-and-tone.md.

Примеры::

    from services import responses as resp

    await message.answer(resp.success("Сообщение закреплено."))
    await message.answer(resp.error("Не получилось закрепить сообщение.",
                                    hint="Проверьте права бота в беседе."))
    await message.answer(resp.denied("Недостаточно прав.",
                                     hint="Нужен уровень: ЗГС"))

Доменные ошибки (``packages/domain/errors.py``) можно превратить в готовый текст
через :func:`from_domain_error`, а хендлеры — обернуть в :func:`safe_handler`,
чтобы неожиданные исключения не «утекали» пользователю сырым текстом.
"""

from __future__ import annotations

import functools
import logging
from collections.abc import Awaitable, Callable
from typing import Any, ParamSpec, TypeVar

from packages.domain.errors import (
    DomainError,
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)

logger = logging.getLogger(__name__)

# --- Статус-глифы (канон, см. docs/voice-and-tone.md) ------------------------
GLYPH_DENIED = "⛔"
GLYPH_ERROR = "❌"
GLYPH_SUCCESS = "✅"
GLYPH_WARN = "⚠️"
GLYPH_INFO = "ℹ️"
GLYPH_EMPTY = "📭"
GLYPH_WORKING = "⚙️"

# Дружелюбный текст на случай непойманного исключения.
GENERIC_ERROR_TEXT = "Что-то пошло не так. Попробуйте ещё раз чуть позже."


def _format(glyph: str, text: str, hint: str | None = None) -> str:
    """Собрать сообщение вида ``<глиф> <суть>\n<подсказка>``."""
    body = f"{glyph} {text.strip()}"
    if hint:
        body = f"{body}\n{hint.strip()}"
    return body


def success(text: str, hint: str | None = None) -> str:
    """Успешное действие. Кнопка «Сохранить» → «Сохранено»."""
    return _format(GLYPH_SUCCESS, text, hint)


def error(text: str, hint: str | None = None) -> str:
    """Ошибка или неверный ввод. Суть + как исправить."""
    return _format(GLYPH_ERROR, text, hint)


def denied(text: str = "Недостаточно прав.", hint: str | None = None) -> str:
    """Нет доступа / запрещено."""
    return _format(GLYPH_DENIED, text, hint)


def warn(text: str, hint: str | None = None) -> str:
    """Предупреждение."""
    return _format(GLYPH_WARN, text, hint)


def info(text: str, hint: str | None = None) -> str:
    """Нейтральная информация."""
    return _format(GLYPH_INFO, text, hint)


def empty(text: str, hint: str | None = None) -> str:
    """Пустое состояние — приглашение к действию."""
    return _format(GLYPH_EMPTY, text, hint)


def working(text: str, hint: str | None = None) -> str:
    """Длительное действие в процессе."""
    return _format(GLYPH_WORKING, text, hint)


def from_domain_error(exc: DomainError) -> str:
    """Превратить доменную ошибку в человечный текст для пользователя."""
    text = str(exc).strip()
    if isinstance(exc, PermissionDeniedError):
        return denied(text or "Недостаточно прав.")
    if isinstance(exc, NotFoundError):
        return error(text or "Ничего не нашлось по запросу.")
    if isinstance(exc, ValidationError):
        return error(text or "Проверьте введённые данные.")
    return error(text or GENERIC_ERROR_TEXT)


P = ParamSpec("P")
R = TypeVar("R")


def safe_handler(
    func: Callable[P, Awaitable[R]],
) -> Callable[P, Awaitable[R | None]]:
    """Обёртка хендлера: доменные ошибки → человечный ответ, прочие → лог + мягкий текст.

    Гарантирует, что сырой текст исключения (``{exc}``) никогда не попадёт
    пользователю. Ожидает, что первым позиционным аргументом идёт ``message``
    с методом ``answer`` (как у хендлеров vkbottle).
    """

    @functools.wraps(func)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R | None:
        message: Any = args[0] if args else None
        try:
            return await func(*args, **kwargs)
        except DomainError as exc:
            if message is not None and hasattr(message, "answer"):
                await message.answer(from_domain_error(exc))
            return None
        except Exception:  # noqa: BLE001 — намеренно ловим всё, чтобы не «утекло»
            logger.exception("Необработанная ошибка в хендлере %s", func.__name__)
            if message is not None and hasattr(message, "answer"):
                await message.answer(error(GENERIC_ERROR_TEXT))
            return None

    return wrapper
