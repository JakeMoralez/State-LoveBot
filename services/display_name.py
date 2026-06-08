"""Системные ники (/setnick) и кликабельные пинги."""

from __future__ import annotations

import re

from vkbottle import API

from database.repository.user_repo import UserRepository

_TAGGED_USERNAME = re.compile(r"^@?\S+\s+\[[^\]]+\]\s+(.+)$")


class DisplayNameService:
    def __init__(self, api: API) -> None:
        self.api = api

    @staticmethod
    def _clean(value: str | None) -> str | None:
        if not value:
            return None
        cleaned = value.strip()
        return cleaned or None

    @classmethod
    def normalize(cls, value: str | None) -> str | None:
        """Короткий ник без декораций (для /me и т.п.)."""
        raw = cls._clean(value)
        if not raw:
            return None

        from_tag = cls._nickname_from_username(raw)
        if from_tag:
            return from_tag

        if "[" in raw or raw.startswith("@"):
            return None

        if " " in raw:
            return None

        return raw.lstrip("@")

    @staticmethod
    def _nickname_from_username(username: str) -> str | None:
        match = _TAGGED_USERNAME.match(username.strip())
        if match:
            return match.group(1).strip()
        return None

    @classmethod
    def sanitize_vk_label(cls, name: str, *, vk_id: int | None = None) -> str:
        """Текст внутри [id|label]: замена только при выводе, в БД ник не меняется."""
        label = (name or "").strip().replace("\n", " ")
        label = label.replace("|", "｜")
        label = label.replace("[", "［").replace("]", "］")
        label = re.sub(r"\s+", " ", label).strip()
        if label:
            return label
        return f"id{vk_id}" if vk_id else "id"

    @classmethod
    def nick_link(cls, vk_id: int, nickname: str) -> str:
        """Кликабельный пинг: [id|никнейм]."""
        raw = (nickname or "").strip().replace("\n", " ")
        label = cls.sanitize_vk_label(raw, vk_id=vk_id)
        return f"[id{vk_id}|{label}]"

    async def get_ping_nickname(self, vk_id: int) -> str | None:
        """Ник из /setnick — только поле nickname в БД."""
        user = await UserRepository.get_by_vk_id(vk_id)
        if user and user.nickname and user.nickname.strip():
            return user.nickname.strip()
        return None

    @staticmethod
    async def get_raw_nickname(vk_id: int, api: API) -> str:
        user = await UserRepository.get_by_vk_id(vk_id)
        if user and user.nickname and user.nickname.strip():
            return user.nickname.strip()
        if user and user.username and user.username.strip():
            return user.username.strip()
        svc = DisplayNameService(api)
        return await svc.get_vk_full_name(vk_id)

    async def _fetch_vk_user(self, vk_id: int):
        try:
            users = await self.api.users.get(user_ids=[vk_id])
            if users:
                return users[0]
        except Exception:
            pass
        return None

    async def get_vk_full_name(self, vk_id: int) -> str:
        vk_user = await self._fetch_vk_user(vk_id)
        if vk_user:
            name = f"{vk_user.first_name} {vk_user.last_name}".strip()
            if name:
                return name
        return f"id{vk_id}"

    async def get_nickname(self, vk_id: int) -> str:
        nick = await self.get_ping_nickname(vk_id)
        if nick:
            return self.normalize(nick) or nick

        user = await UserRepository.get_by_vk_id(vk_id)
        if user and user.username:
            from_username = self.normalize(user.username)
            if from_username:
                return from_username

        return await self.get_vk_full_name(vk_id)

    async def get_known_nickname(self, vk_id: int) -> str | None:
        return await self.get_ping_nickname(vk_id)

    async def get_invite_label(self, vk_id: int) -> str:
        nick = await self.get_ping_nickname(vk_id)
        if nick:
            return nick
        return await self.get_vk_full_name(vk_id)

    async def mention_user(self, vk_id: int) -> str:
        """Пинг: системный ник из БД, кликабельный."""
        nick = await self.get_ping_nickname(vk_id)
        if nick:
            return self.nick_link(vk_id, nick)

        full = await self.get_vk_full_name(vk_id)
        if full and not full.startswith("id"):
            return self.nick_link(vk_id, full)
        return f"[id{vk_id}|id{vk_id}]"

    async def link_user(self, vk_id: int) -> str:
        """Ссылка [id|ник] — отправлять с disable_mentions=1 (без уведомления)."""
        return await self.mention_user(vk_id)

    async def format_actor_badge(self, vk_id: int, server_id: int) -> str:
        """Кликабельный инициатор: ［ЗГС ЦА］ Isaac_Grozny."""
        from middlewares.access import AccessChecker

        level = await UserRepository.get_access_level(vk_id, server_id)
        title = AccessChecker.level_name(level) if level else "—"
        nick = await self.get_nickname(vk_id)
        label = self.sanitize_vk_label(f"［{title}］ {nick}", vk_id=vk_id)
        return f"[id{vk_id}|{label}]"

    async def format_kick_announce(
        self,
        *,
        target_id: int,
        actor_id: int,
        server_id: int,
        reason: str | None,
    ) -> str:
        target_m = await self.link_user(target_id)
        actor_m = await self.link_user(actor_id)
        reason_text = reason.strip() if reason and reason.strip() else "."
        return (
            f"🚫 {target_m} был(а) исключён(а) по запросу {actor_m}.\n"
            f"📝 Причина: {reason_text}"
        )

    async def profile_link_user(self, vk_id: int) -> str:
        return await self.link_user(vk_id)

    @staticmethod
    def mention(vk_id: int, name: str) -> str:
        return DisplayNameService.nick_link(vk_id, name)
