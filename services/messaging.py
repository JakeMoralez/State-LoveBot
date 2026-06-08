"""Сообщения с пингами участников беседы."""

from __future__ import annotations

import logging
import random

from vkbottle import API

from config.settings import VK_GROUP_ID, VK_USER_TOKEN
from database.repository.user_repo import UserRepository
from services.display_name import DisplayNameService

logger = logging.getLogger(__name__)


class MessagingService:
    def __init__(
        self,
        api: API,
        *,
        group_id: int | None = None,
        user_api: API | None = None,
    ) -> None:
        self.api = api
        self.group_id = group_id or VK_GROUP_ID or None
        self.user_api = user_api
        self.names = DisplayNameService(api)

    @staticmethod
    def _parse_member_ids(raw: dict) -> list[int]:
        items = raw.get("items") or raw.get("response", {}).get("items") or []
        ids: list[int] = []
        for item in items:
            if isinstance(item, dict):
                mid = item.get("member_id")
            else:
                mid = getattr(item, "member_id", None)
            if mid and mid > 0:
                ids.append(int(mid))
        return ids

    async def _fetch_members_raw(
        self,
        api: API,
        peer_id: int,
        *,
        offset: int,
        count: int,
        with_group_id: bool,
    ) -> list[int]:
        params: dict = {
            "peer_id": peer_id,
            "count": count,
            "offset": offset,
        }
        if with_group_id and self.group_id:
            params["group_id"] = self.group_id

        try:
            raw = await api.request("messages.getConversationMembers", params)
            if isinstance(raw, dict) and "response" in raw:
                return self._parse_member_ids(raw["response"])
            if isinstance(raw, dict):
                return self._parse_member_ids(raw)
        except Exception:
            pass

        data = await api.messages.get_conversation_members(**params)
        return self._parse_member_ids({"items": data.items or []})

    async def get_member_ids(self, peer_id: int) -> list[int]:
        if peer_id < 2_000_000_000:
            return []

        apis: list[tuple[API, str]] = [(self.api, "group")]
        if self.user_api:
            apis.append((self.user_api, "user"))
        elif VK_USER_TOKEN:
            apis.append((API(token=VK_USER_TOKEN), "user"))

        page_size = 200
        for api, label in apis:
            for with_group_id in (False, True) if label == "group" else (False,):
                ids: list[int] = []
                offset = 0
                try:
                    while True:
                        page = await self._fetch_members_raw(
                            api,
                            peer_id,
                            offset=offset,
                            count=page_size,
                            with_group_id=with_group_id,
                        )
                        if not page:
                            break
                        ids.extend(page)
                        if len(page) < page_size:
                            break
                        offset += page_size

                    if ids:
                        logger.info(
                            "get_member_ids peer=%s count=%s api=%s group_id=%s",
                            peer_id,
                            len(ids),
                            label,
                            with_group_id,
                        )
                        return ids
                except Exception as exc:
                    logger.warning(
                        "get_member_ids peer=%s api=%s group_id=%s: %s",
                        peer_id,
                        label,
                        with_group_id,
                        exc,
                    )

        logger.warning(
            "get_member_ids: пустой список peer=%s (нужен VK_USER_TOKEN или права бота в беседе)",
            peer_id,
        )
        return []

    async def _pingable_members(
        self,
        member_ids: list[int],
        server_id: int,
        *,
        exclude_id: int | None = None,
    ) -> list[int]:
        result: list[int] = []
        for mid in member_ids:
            if exclude_id and mid == exclude_id:
                continue
            if await UserRepository.is_pingable_in_chat(mid, server_id):
                result.append(mid)
        return result

    async def format_members_list(self, peer_id: int, server_id: int) -> str:
        member_ids = await self.get_member_ids(peer_id)
        if not member_ids:
            return "❌ Не удалось получить список участников беседы."

        visible = await self._pingable_members(member_ids, server_id)
        if not visible:
            return "📭 Нет участников для отображения."

        lines = [f"👥 Участники беседы ({len(visible)}):"]
        for mid in sorted(visible):
            lines.append(f"• {await self.names.link_user(mid)}")
        return "\n".join(lines)

    async def build_alert_message(
        self,
        *,
        peer_id: int,
        text: str,
        sender_vk_id: int,
        server_id: int,
    ) -> str:
        member_ids = await self._pingable_members(
            await self.get_member_ids(peer_id),
            server_id,
            exclude_id=sender_vk_id,
        )

        pings = "".join(
            DisplayNameService.nick_link(mid, "👤") for mid in member_ids
        )

        sender = await self.names.link_user(sender_vk_id)

        lines = ["❗ Оповещение❗", ""]
        if pings:
            lines.append(pings)
        lines.extend(["", f"📍 {text}", "", f"🗣 {sender}"])
        return "\n".join(lines)

    async def format_invite_notice(self, vk_id: int) -> str:
        link = await self.names.link_user(vk_id)
        return f"➕ В беседу добавлен: {link}"

    @staticmethod
    def random_id() -> int:
        return random.randint(1, 2_000_000_000)
