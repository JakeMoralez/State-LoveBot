"""Сообщения с пингами участников беседы."""

from __future__ import annotations

import logging
import random

from vkbottle import API
from vkbottle.bot import Message

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

        names = DisplayNameService(self.api, server_id)
        lines = [f"👥 Участники беседы ({len(visible)}):"]
        for mid in sorted(visible):
            lines.append(f"• {await names.link_user(mid)}")
        return "\n".join(lines)

    @staticmethod
    def extract_photo_attachments(message: Message) -> str | None:
        try:
            strings = message.get_attachment_strings()
        except Exception:
            return None
        if not strings:
            return None
        photos = [item for item in strings if item.startswith("photo")]
        return ",".join(photos) if photos else None

    @staticmethod
    def attachment_preview_label(attachments: str | None) -> str | None:
        if not attachments:
            return None
        count = len(attachments.split(","))
        word = "фото" if count == 1 else "фото"
        return f"📎 Вложение: {count} {word}"

    async def _alert_member_ids(
        self,
        peer_id: int,
        server_id: int,
        *,
        sender_vk_id: int,
    ) -> list[int]:
        return await self._pingable_members(
            await self.get_member_ids(peer_id),
            server_id,
            exclude_id=sender_vk_id,
        )

    @staticmethod
    def _format_alert_body(*, sender_label: str, member_line: str, text: str) -> str:
        lines = [f"❗ Оповещение от {sender_label} ❗", ""]
        if member_line:
            lines.append(member_line)
            lines.append("")
        lines.append(f"📍 {text}")
        return "\n".join(lines)

    async def _build_alert_content(
        self,
        *,
        peer_id: int,
        text: str,
        sender_vk_id: int,
        server_id: int,
    ) -> str:
        member_ids = await self._alert_member_ids(
            peer_id, server_id, sender_vk_id=sender_vk_id
        )
        pings = "".join(
            DisplayNameService.nick_link(mid, "👤") for mid in member_ids
        )
        names = DisplayNameService(self.api, server_id)
        sender = await names.mention_user(sender_vk_id, server_id)
        return self._format_alert_body(
            sender_label=sender,
            member_line=pings,
            text=text,
        )

    async def build_alert_message(
        self,
        *,
        peer_id: int,
        text: str,
        sender_vk_id: int,
        server_id: int,
    ) -> str:
        return await self._build_alert_content(
            peer_id=peer_id,
            text=text,
            sender_vk_id=sender_vk_id,
            server_id=server_id,
        )

    async def build_alert_preview(
        self,
        *,
        peer_id: int,
        text: str,
        sender_vk_id: int,
        server_id: int,
    ) -> str:
        return await self._build_alert_content(
            peer_id=peer_id,
            text=text,
            sender_vk_id=sender_vk_id,
            server_id=server_id,
        )

    async def format_welcome_notice(
        self,
        vk_id: int,
        *,
        invited_by: int | None = None,
        server_id: int | None = None,
    ) -> str:
        names = DisplayNameService(self.api, server_id)
        link = await names.link_user(vk_id)
        if invited_by and invited_by > 0 and invited_by != vk_id:
            inviter = await names.link_user(invited_by)
            return f"➕ {inviter} пригласил(а) {link}."
        return f"➕ {link} вступил(а) в беседу."

    @staticmethod
    def random_id() -> int:
        return random.randint(1, 2_000_000_000)
