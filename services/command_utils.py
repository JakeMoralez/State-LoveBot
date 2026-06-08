"""Двойные префиксы команд: /команда и !команда."""

from __future__ import annotations


def dual(name: str) -> list[str]:
    return [f"/{name}", f"!{name}"]


def dual_args(name: str, args: str = "<args>") -> list[str]:
    return [
        f"/{name}",
        f"!{name}",
        f"/{name} {args}",
        f"!{name} {args}",
    ]


def matches_cmd(text: str, name: str) -> bool:
    t = (text or "").strip().lower()
    for prefix in (f"/{name.lower()}", f"!{name.lower()}"):
        if t == prefix or t.startswith(f"{prefix} "):
            return True
    return False


def strip_cmd(text: str, name: str) -> str:
    raw = (text or "").strip()
    for prefix in (f"/{name}", f"!{name}", f"/{name.upper()}", f"!{name.upper()}"):
        if raw.lower().startswith(prefix.lower()):
            return raw[len(prefix) :].strip()
    return raw


def parse_forum_thread(text: str, names: tuple[str, ...]) -> int | None:
    from services.forum_api import ForumService

    for name in names:
        for prefix in (f"!{name}", f"/{name}"):
            thread_id, _ = ForumService.parse_forum_command(text, prefix)
            if thread_id:
                return thread_id
    return None
