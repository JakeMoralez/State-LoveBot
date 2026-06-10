"""Контекст активного сервера для разработчика (/meserver)."""

from __future__ import annotations

_dev_server_overrides: dict[int, int] = {}


def get_dev_server_override(vk_id: int) -> int | None:
    return _dev_server_overrides.get(vk_id)


def set_dev_server_override(vk_id: int, server_id: int) -> None:
    _dev_server_overrides[vk_id] = server_id


def clear_dev_server_override(vk_id: int) -> None:
    _dev_server_overrides.pop(vk_id, None)
