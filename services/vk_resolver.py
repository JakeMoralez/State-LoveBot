"""Разбор VK-ссылок, упоминаний, ID и никнеймов из БД."""

from __future__ import annotations

import re
from dataclasses import dataclass

from vkbottle import API

from database.repository.user_repo import UserRepository

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
    def __init__(self, api: API, server_id: int | None = None) -> None:
        self.api = api
        self.server_id = server_id

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

    @staticmethod
    def _is_explicit_vk_id(ref: str) -> bool:
        """Числовой id или ссылка vk.com/vk.ru/id… — не ник бота."""
        ref = ref.strip()
        vk_id, _ = VKResolver.parse_reference(ref)
        if vk_id is not None:
            return True
        low = ref.lower()
        return "vk.com" in low or "vk.ru" in low

    async def _resolve_vk_id(self, vk_id: int) -> ResolvedUser:
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

    async def _resolve_vk_screen(self, screen_name: str) -> ResolvedUser | None:
        users = await self.api.users.get(user_ids=[screen_name])
        if not users:
            return None
        u = users[0]
        name = f"{u.first_name} {u.last_name}".strip()
        return ResolvedUser(
            vk_id=u.id,
            username=screen_name,
            display_name=name,
        )

    async def _resolve_by_nickname(
        self,
        query: str,
        server_id: int | None = None,
    ) -> tuple[ResolvedUser | None, str | None]:
        """Поиск по нику бота на сервере: точное совпадение, затем частичное."""
        sid = server_id if server_id is not None else self.server_id
        query = query.strip().lstrip("@")
        if not query or query.isdigit() or not sid:
            return None, None

        user = await UserRepository.get_by_nickname(query, sid)
        if user:
            nick = await UserRepository.get_nickname(user.vk_id, sid)
            return ResolvedUser(
                vk_id=user.vk_id,
                username=user.username,
                display_name=nick,
            ), None

        user = await UserRepository.get_by_username(query)
        if user:
            nick = await UserRepository.get_nickname(user.vk_id, sid)
            return ResolvedUser(
                vk_id=user.vk_id,
                username=user.username,
                display_name=nick or user.username,
            ), None

        matches = await UserRepository.search_users(query, sid, limit=8)
        if not matches:
            return None, None
        if len(matches) == 1:
            u = matches[0]
            nick = await UserRepository.get_nickname(u.vk_id, sid)
            return ResolvedUser(
                vk_id=u.vk_id,
                username=u.username,
                display_name=nick or u.username,
            ), None

        lines = [f"❌ Найдено несколько пользователей по «{query}»:"]
        for u in matches[:5]:
            nick = await UserRepository.get_nickname(u.vk_id, sid)
            label = nick or u.username or str(u.vk_id)
            lines.append(f"• {label} (id{u.vk_id})")
        lines.append("Уточните ник или укажите VK-ссылку / id.")
        return None, "\n".join(lines)

    async def resolve(self, raw: str) -> ResolvedUser | None:
        resolved, _err = await self.resolve_with_hint(raw)
        return resolved

    async def resolve_with_hint(
        self,
        raw: str,
        server_id: int | None = None,
    ) -> tuple[ResolvedUser | None, str | None]:
        ref = self.extract_reference(raw)
        vk_id, screen_name = self.parse_reference(ref)

        if vk_id is not None and self._is_explicit_vk_id(ref):
            return await self._resolve_vk_id(vk_id), None

        lookup = (screen_name or ref).strip().lstrip("@")
        if lookup:
            nick_resolved, hint = await self._resolve_by_nickname(lookup, server_id)
            if hint:
                return None, hint
            if nick_resolved:
                return nick_resolved, None

        if vk_id is not None:
            return await self._resolve_vk_id(vk_id), None

        if screen_name:
            vk_resolved = await self._resolve_vk_screen(screen_name)
            if vk_resolved:
                return vk_resolved, None

        return None, None

    async def resolve_from_message(
        self,
        args: str,
        *,
        reply_from_id: int | None = None,
    ) -> ResolvedUser | None:
        resolved, _err = await self.resolve_from_message_with_hint(
            args, reply_from_id=reply_from_id
        )
        return resolved

    async def resolve_from_message_with_hint(
        self,
        args: str,
        *,
        reply_from_id: int | None = None,
        server_id: int | None = None,
    ) -> tuple[ResolvedUser | None, str | None]:
        if reply_from_id and reply_from_id > 0:
            return await self.resolve_with_hint(str(reply_from_id), server_id)
        raw = args.strip()
        if raw:
            return await self.resolve_with_hint(raw, server_id)
        return None, None
