"""Отображение сервера в /me и сообщениях."""

from __future__ import annotations

from database.models.server import Server


def _short_name(server: Server) -> str:
    tag = (server.tag or "").strip()
    if tag:
        return tag

    name = (server.name or "").strip()
    if not name:
        return f"№{server.id}"

    for prefix in ("Arizona RP ", "Arizona №", "Arizona "):
        if name.startswith(prefix):
            rest = name[len(prefix) :].strip()
            if rest:
                return rest

    if " " in name:
        return name.split()[-1]
    return name


def format_server_label(server: Server | None, server_id: int) -> str:
    """Love [№30]"""
    if server:
        return f"{_short_name(server)} [№{server.id}]"
    return f"№{server_id}"


def format_judge_forum_hint(forum_id: int) -> str:
    return f"forums/{forum_id}/"
