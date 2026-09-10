"""Resolve effective min_level for commands (defaults + per-server overrides)."""

from __future__ import annotations

import time
from typing import Any

from database.models.command_access import CommandAccessOverride
from services.command_catalog import COMMAND_CATALOG, get_command_entry

_CACHE: dict[int, tuple[float, dict[str, int]]] = {}
_CACHE_TTL = 30.0


def invalidate_command_access_cache(server_id: int | None = None) -> None:
    if server_id is None:
        _CACHE.clear()
        return
    _CACHE.pop(int(server_id), None)


async def _load_overrides(server_id: int) -> dict[str, int]:
    now = time.monotonic()
    cached = _CACHE.get(server_id)
    if cached and now - cached[0] < _CACHE_TTL:
        return cached[1]
    rows = await CommandAccessOverride.filter(server_id=server_id).all()
    mapping = {row.command_key: int(row.min_level) for row in rows}
    _CACHE[server_id] = (now, mapping)
    return mapping


async def effective_min_level(server_id: int, command_key: str, default: int) -> int:
    entry = get_command_entry(command_key)
    if entry is not None and not entry.overridable:
        return entry.default_min_level
    overrides = await _load_overrides(server_id)
    if command_key in overrides:
        return int(overrides[command_key])
    if entry is not None:
        return entry.default_min_level
    return default


async def list_command_access(server_id: int) -> dict[str, Any]:
    overrides = await _load_overrides(server_id)
    items = []
    for entry in COMMAND_CATALOG:
        ov = overrides.get(entry.key)
        items.append(
            {
                "key": entry.key,
                "label": entry.label,
                "category": entry.category,
                "default_min_level": entry.default_min_level,
                "overridable": entry.overridable,
                "min_level": ov if ov is not None else entry.default_min_level,
                "is_override": ov is not None,
            }
        )
    return {"server_id": server_id, "items": items}


async def save_command_access(server_id: int, updates: list[dict[str, Any]]) -> dict[str, Any]:
    """updates: [{key, min_level|null}] — null resets to default."""
    for item in updates:
        key = str(item.get("key") or "").strip()
        entry = get_command_entry(key)
        if entry is None:
            raise ValueError(f"Неизвестная команда: {key}")
        if not entry.overridable:
            raise ValueError(f"Команда /{key} нельзя менять из панели")
        if "min_level" not in item or item["min_level"] is None:
            await CommandAccessOverride.filter(server_id=server_id, command_key=key).delete()
            continue
        level = int(item["min_level"])
        if level < 0 or level > 11:
            raise ValueError(f"Уровень для /{key}: 0–11")
        await CommandAccessOverride.update_or_create(
            server_id=server_id,
            command_key=key,
            defaults={"min_level": level},
        )
    invalidate_command_access_cache(server_id)
    return await list_command_access(server_id)
