"""VK-администрирование бесед: мут, админы, название, онлайн, поиск."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from vkbottle import API

from config.settings import VK_GROUP_ID, VK_USER_TOKEN
from database.repository.user_repo import UserRepository
from services.display_name import DisplayNameService
from services.vk_resolver import VKResolver

logger = logging.getLogger(__name__)

_DURATION_RE = re.compile(
    r"^(\d+)\s*(s|с|sec|сек|m|м|min|мин|h|ч|hour|час|d|д|day|дн)$",
    re.IGNORECASE,
)


@dataclass
class FoundUser:
    vk_id: int
    label: str
    source: str


class ChatAdminService:
    def __init__(self, api: API) -> None:
        self.api = api
        self.names = DisplayNameService(api)
        self.resolver = VKResolver(api)

    @staticmethod
    def peer_to_chat_id(peer_id: int) -> int:
        return int(peer_id - 2_000_000_000)

    @staticmethod
    def parse_mute_args(args: str) -> tuple[str | None, int | None, str | None]:
        """target_raw, seconds, reason — для /mute [@user] [время] [причина]."""
        raw = (args or "").strip()
        if not raw:
            return None, None, None

        parts = raw.split()
        if len(parts) == 1:
            seconds = ChatAdminService.parse_duration(parts[0])
            if seconds:
                return None, seconds, None
            return parts[0], None, None

        target = parts[0]
        rest = parts[1:]
        for i, token in enumerate(rest):
            seconds = ChatAdminService.parse_duration(token)
            if seconds:
                reason = " ".join(rest[i + 1 :]).strip() or None
                return target, seconds, reason

        return target, None, " ".join(rest).strip() or None

    @staticmethod
    def parse_duration(raw: str) -> int | None:
        raw = (raw or "").strip().lower()
        if raw.isdigit():
            return int(raw)
        match = _DURATION_RE.match(raw)
        if not match:
            return None
        amount = int(match.group(1))
        unit = match.group(2).lower()
        if unit in ("s", "с", "sec", "сек"):
            return amount
        if unit in ("m", "м", "min", "мин"):
            return amount * 60
        if unit in ("h", "ч", "hour", "час"):
            return amount * 3600
        if unit in ("d", "д", "day", "дн"):
            return amount * 86400
        return None

    @staticmethod
    def format_duration(seconds: int) -> str:
        if seconds < 60:
            return f"{seconds} сек."
        minutes = seconds // 60
        if minutes < 60:
            return f"{minutes} мин."
        hours = minutes // 60
        rest = minutes % 60
        if hours < 24:
            return f"{hours} ч. {rest} мин." if rest else f"{hours} ч."
        days = hours // 24
        hours = hours % 24
        return f"{days} д. {hours} ч." if hours else f"{days} д."

    async def set_chat_title(self, peer_id: int, title: str) -> tuple[bool, str]:
        title = title.strip()
        if not title:
            return False, "Укажите название."
        if len(title) > 128:
            return False, "Название слишком длинное (макс. 128)."
        try:
            await self.api.messages.edit_chat(
                chat_id=self.peer_to_chat_id(peer_id),
                title=title,
            )
            return True, title
        except Exception as exc:
            logger.warning("edit_chat failed peer=%s: %s", peer_id, exc)
            return False, str(exc)

    async def mute_member(
        self,
        peer_id: int,
        target_id: int,
        *,
        seconds: int | None,
    ) -> tuple[bool, str]:
        params: dict[str, object] = {
            "peer_id": peer_id,
            "member_ids": str(target_id),
            "action": "ro",
        }
        if seconds is not None and seconds > 0:
            params["for"] = seconds

        apis: list[tuple[API, bool]] = [(self.api, True)]
        if VK_USER_TOKEN:
            apis.append((API(token=VK_USER_TOKEN), False))

        last_err = ""
        for api, use_group_id in apis:
            call_params = dict(params)
            if use_group_id and VK_GROUP_ID:
                call_params["group_id"] = VK_GROUP_ID
            try:
                await api.request(
                    "messages.changeConversationMemberRestrictions",
                    call_params,
                )
                return True, ""
            except Exception as exc:
                last_err = str(exc)
                logger.warning(
                    "mute failed peer=%s target=%s group=%s: %s",
                    peer_id,
                    target_id,
                    use_group_id,
                    exc,
                )
        return False, last_err or "Нет прав у бота на мут"

    async def invite_member(
        self,
        peer_id: int,
        target_id: int,
    ) -> tuple[bool, str]:
        """Добавить пользователя в беседу (нужен VK_USER_TOKEN с messages)."""
        if peer_id < 2_000_000_000:
            return False, "Только в беседах"
        if not VK_USER_TOKEN:
            return False, "Не настроен VK_USER_TOKEN (нужен user-токен с правом «Сообщения»)"

        chat_id = self.peer_to_chat_id(peer_id)
        user_api = API(token=VK_USER_TOKEN)
        try:
            await user_api.messages.add_chat_user(
                chat_id=chat_id,
                user_id=target_id,
            )
            return True, ""
        except Exception as exc:
            logger.warning(
                "invite failed peer=%s target=%s: %s",
                peer_id,
                target_id,
                exc,
            )
            raw = str(exc).lower()
            if "already" in raw or "уже" in raw:
                return False, "Пользователь уже в беседе"
            if "privacy" in raw or "приват" in raw:
                return False, "Приватность: пользователь запретил приглашения"
            if "access" in raw or "denied" in raw or "15" in raw:
                return False, "Нет прав: аккаунт токена должен быть админом беседы"
            if "not found" in raw or "can't add" in raw or "cannot add" in raw:
                return False, "Не удалось добавить (закрытый профиль / нет в друзьях?)"
            msg = str(exc)
            if len(msg) > 120:
                msg = msg[:117] + "..."
            return False, msg or "Ошибка VK API"

    async def unmute_member(self, peer_id: int, target_id: int) -> tuple[bool, str]:
        params = {
            "peer_id": peer_id,
            "member_ids": str(target_id),
            "action": "rw",
        }
        if VK_GROUP_ID:
            params["group_id"] = VK_GROUP_ID
        try:
            await self.api.request(
                "messages.changeConversationMemberRestrictions",
                params,
            )
            return True, ""
        except Exception as exc:
            logger.warning("unmute failed peer=%s target=%s: %s", peer_id, target_id, exc)
            return False, str(exc)

    async def get_member_ids(self, peer_id: int) -> list[int]:
        from services.messaging import MessagingService

        return await MessagingService(self.api).get_member_ids(peer_id)

    async def format_online_list(self, peer_id: int) -> str:
        member_ids = await self.get_member_ids(peer_id)
        if not member_ids:
            return "❌ Не удалось получить участников беседы."

        online: list[tuple[int, str]] = []
        offline = 0
        batch_size = 1000
        for offset in range(0, len(member_ids), batch_size):
            batch = member_ids[offset : offset + batch_size]
            try:
                users = await self.api.users.get(
                    user_ids=batch,
                    fields=["online", "last_seen"],
                )
            except Exception as exc:
                logger.warning("users.get online peer=%s: %s", peer_id, exc)
                return f"❌ Ошибка VK API: {exc}"

            for user in users:
                uid = user.id
                if getattr(user, "online", 0):
                    online.append((uid, "🟢"))
                else:
                    offline += 1

        if not online:
            return f"📭 Сейчас онлайн никого нет ({len(member_ids)} в беседе)."

        lines = [f"🟢 Онлайн ({len(online)} из {len(member_ids)}):"]
        for uid, mark in sorted(online, key=lambda x: x[0]):
            link = await self.names.link_user(uid)
            lines.append(f"{mark} {link}")
        lines.append(f"\n⚫ Оффлайн: {offline}")
        return "\n".join(lines)

    async def find_users(
        self,
        query: str,
        server_id: int,
        *,
        limit: int = 10,
    ) -> list[FoundUser]:
        query = (query or "").strip()
        if not query:
            return []

        found: list[FoundUser] = []
        seen: set[int] = set()

        db_rows = await UserRepository.search_users(query, server_id, limit=limit)
        for user in db_rows:
            if user.vk_id in seen:
                continue
            seen.add(user.vk_id)
            nick = await UserRepository.get_nickname(user.vk_id, server_id)
            label = nick or user.username or f"id{user.vk_id}"
            found.append(FoundUser(user.vk_id, label, "база"))

        if len(found) < limit and not query.startswith("id"):
            resolved, _ = await self.resolver.resolve_with_hint(query, server_id)
            if resolved and resolved.vk_id not in seen:
                seen.add(resolved.vk_id)
                label = resolved.display_name or resolved.username or f"id{resolved.vk_id}"
                found.append(FoundUser(resolved.vk_id, label, "vk"))

        if len(found) < limit:
            try:
                search = await self.api.users.search(
                    q=query.lstrip("@"),
                    count=min(5, limit - len(found)),
                    fields=["domain"],
                )
                items = getattr(search, "items", None) or []
                for user in items:
                    uid = user.id
                    if not uid or uid in seen:
                        continue
                    seen.add(uid)
                    domain = getattr(user, "domain", None)
                    first = getattr(user, "first_name", "") or ""
                    last = getattr(user, "last_name", "") or ""
                    label = domain or f"{first} {last}".strip() or f"id{uid}"
                    found.append(FoundUser(uid, label, "поиск VK"))
            except Exception as exc:
                logger.warning("users.search q=%s: %s", query, exc)

        return found[:limit]

    async def format_find_results(self, query: str, server_id: int) -> str:
        rows = await self.find_users(query, server_id)
        if not rows:
            return f"❌ По запросу «{query}» никого не найдено."

        names = DisplayNameService(self.api, server_id)
        lines = [f"🔍 Найдено по «{query}» ({len(rows)}):"]
        for row in rows:
            link = await names.link_user(row.vk_id)
            lines.append(f"• {link}")
        return "\n".join(lines)

    async def format_registration_date(self, vk_id: int) -> str:
        from services.vk_registration import resolve_registration_date

        try:
            users = await self.api.users.get(user_ids=[vk_id], fields=["domain"])
        except Exception as exc:
            return f"❌ Ошибка VK API: {exc}"
        if not users:
            return "❌ Пользователь не найден."

        link = await self.names.link_user(vk_id)
        reg_dt, source = await resolve_registration_date(vk_id)
        if not reg_dt:
            return (
                f"📅 {link}\n"
                "❌ Дата регистрации VK недоступна.\n"
                "💡 VK не отдаёт её через API; foaf.php тоже не ответил."
            )

        reg_str = reg_dt.strftime("%d.%m.%Y")
        if source == "estimate":
            return (
                f"📅 {link}\n"
                f"🗓 Регистрация VK: ~{reg_str} (оценка по ID)"
            )
        return f"📅 {link}\n🗓 Регистрация VK: {reg_str}"
