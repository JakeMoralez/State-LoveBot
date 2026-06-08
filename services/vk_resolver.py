"""Разбор VK-ссылок, упоминаний и ID."""

from __future__ import annotations

import re
from dataclasses import dataclass

from vkbottle import API

# [id123|name], @user, https://vk.com/... https://vk.ru/..., id123, 123456
VK_MENTION_RE = re.compile(
    r"(?:"
    r"\[id(\d+)\|[^\]]+\]"
    r"|@([a-zA-Z0-9_.]+)"
    r"|(?:https?://)?(?:m\.)?(?:vk\.com|vk\.ru)/(?:id(\d+)|([a-zA-Z0-9_.]+))"
    r"|^id(\d+)$"
    r"|^(\d+)$"
    r")",
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
        """Извлекает vk_id или screen_name из строки (в т.ч. vk.com / vk.ru)."""
        raw = raw.strip()
        match = VK_MENTION_RE.search(raw)
        if not match:
            if raw.isdigit():
                return int(raw), None
            if raw.startswith("@"):
                return None, raw[1:]
            return None, raw

        vk_id, screen, url_id, url_screen, id_prefix, digits = match.groups()
        if vk_id:
            return int(vk_id), None
        if screen:
            return None, screen
        if url_id:
            return int(url_id), None
        if url_screen:
            return None, url_screen
        if id_prefix:
            return int(id_prefix), None
        if digits:
            return int(digits), None
        return None, None

    @staticmethod
    def extract_reference(raw: str) -> str:
        """Первое упоминание/ссылка/id в аргументах команды."""
        raw = (raw or "").strip()
        if not raw:
            return ""
        match = VK_MENTION_RE.search(raw)
        if match:
            return match.group(0)
        return raw.split(maxsplit=1)[0]

    async def resolve(self, raw: str) -> ResolvedUser | None:
        ref = self.extract_reference(raw)
        vk_id, screen_name = self.parse_reference(ref)
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
