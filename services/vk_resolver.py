"""Разбор VK-ссылок, упоминаний и ID."""

from __future__ import annotations

import re
from dataclasses import dataclass

from vkbottle import API

VK_MENTION_RE = re.compile(
    r"(?:\[id(\d+)\|[^\]]+\]|@([a-zA-Z0-9_.]+)|https?://vk\.com/(?:id(\d+)|([a-zA-Z0-9_.]+))|^(?:id)?(\d+)$)",
    re.IGNORECASE,
)


@dataclass
class ResolvedUser:
    vk_id: int
    username: str | None = None
    display_name: str | None = None


class VKResolver:
    def __init__(self, api: API) -> None:
        self.api = api

    @staticmethod
    def parse_reference(raw: str) -> tuple[int | None, str | None]:
        """Извлекает vk_id или screen_name из строки."""
        raw = raw.strip()
        match = VK_MENTION_RE.search(raw)
        if not match:
            if raw.isdigit():
                return int(raw), None
            if raw.startswith("@"):
                return None, raw[1:]
            return None, raw
        groups = match.groups()
        if groups[0]:
            return int(groups[0]), None
        if groups[1]:
            return None, groups[1]
        if groups[2]:
            return int(groups[2]), None
        if groups[3]:
            return None, groups[3]
        if groups[4]:
            return int(groups[4]), None
        return None, None

    async def resolve(self, raw: str) -> ResolvedUser | None:
        vk_id, screen_name = self.parse_reference(raw)
        if vk_id:
            users = await self.api.users.get(user_ids=[vk_id])
            if users:
                u = users[0]
                name = f"{u.first_name} {u.last_name}".strip()
                return ResolvedUser(
                    vk_id=u.id,
                    username=getattr(u, "domain", None),
                    display_name=name,
                )
            return ResolvedUser(vk_id=vk_id)

        if screen_name:
            users = await self.api.users.get(user_ids=[screen_name])
            if users:
                u = users[0]
                name = f"{u.first_name} {u.last_name}".strip()
                return ResolvedUser(
                    vk_id=u.id,
                    username=screen_name,
                    display_name=name,
                )
        return None

    async def resolve_from_message(
        self,
        args: str,
        *,
        reply_from_id: int | None = None,
    ) -> ResolvedUser | None:
        if reply_from_id and reply_from_id > 0:
            return await self.resolve(str(reply_from_id))
        raw = args.strip()
        if raw:
            return await self.resolve(raw)
        return None
