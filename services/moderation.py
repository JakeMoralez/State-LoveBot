"""Сервис кика и pullkick."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from vkbottle import API
from vkbottle.exception_factory import VKAPIError

from database.repository.chat_repo import ChatRepository
from database.repository.moderation_repo import ModerationRepository

logger = logging.getLogger(__name__)

_CODE_KICK_REASON: dict[int, str] = {
    15: "Нет прав у бота",
    917: "Бот не в беседе",
    932: "Бот не может работать с этой беседой",
    935: "Пользователь не в беседе",
}


def humanize_kick_error(exc: BaseException | str | None) -> str:
    """Текст для пользователя вместо сырого ответа VK API."""
    if exc is None:
        return "Нет прав у бота"

    code: int | None = None
    msg = ""

    if isinstance(exc, VKAPIError):
        code = getattr(exc, "code", None)
        msg = (exc.error_msg or str(exc)).lower()
    else:
        raw = str(exc).strip()
        if not raw:
            return "Нет прав у бота"
        match = re.search(r"\[(\d+)\]", raw)
        if match:
            code = int(match.group(1))
        msg = raw.lower()

    if code == 15:
        if "can't remove" in msg or "cant remove" in msg:
            return "Нет прав: нельзя исключить (админ беседы?)"
        if "no access to call" in msg:
            return "Нет прав у бота на этот метод"
        return _CODE_KICK_REASON[15]

    if code and code in _CODE_KICK_REASON:
        return _CODE_KICK_REASON[code]

    if "not found in chat" in msg or "not in chat" in msg or "user not found" in msg:
        return "Пользователь не в беседе"
    if "don't have access to this chat" in msg or "no access to this chat" in msg:
        return "Бот не в беседе"
    if "community can't interact" in msg or "cant interact with this peer" in msg:
        return "Бот не может работать с этой беседой"
    if "access denied" in msg:
        return "Нет прав у бота"

    raw_out = exc.error_msg if isinstance(exc, VKAPIError) else str(exc)
    if len(raw_out) > 72:
        return raw_out[:69] + "..."
    return raw_out or "Неизвестная ошибка"


@dataclass
class KickResult:
    peer_id: int
    success: bool
    error: str | None = None
    title: str | None = None


@dataclass
class PullKickReport:
    total: int = 0
    kicked: int = 0
    failed: int = 0
    results: list[KickResult] = field(default_factory=list)

    def summary(self) -> str:
        return f"Исключён из {self.kicked}/{self.total} бесед пула."

    def format_message(
        self,
        *,
        target_label: str,
        pool_name: str,
        reason: str | None = None,
    ) -> str:
        if self.total == 0:
            return "❌ В пуле нет зарегистрированных бесед."

        if self.kicked == self.total:
            header = (
                f"✅ | {target_label} был(а) исключён(а) "
                f"из всех конференций пула «{pool_name}»!"
            )
        elif self.kicked > 0:
            header = (
                f"⚠️ | {target_label} исключён(а) "
                f"из {self.kicked}/{self.total} конференций пула «{pool_name}»"
            )
        else:
            header = (
                f"❌ | Не удалось исключить {target_label} "
                f"из конференций пула «{pool_name}»"
            )

        lines = [header, "", "📂 Список конференций:"]
        for item in self.results:
            name = item.title or f"Беседа {item.peer_id}"
            if item.success:
                lines.append(f"• {name} — Исключён ✅")
            else:
                reason = item.error or "Нет прав у бота"
                lines.append(f"• {name} — {reason} ❌")

        if reason:
            lines.extend(["", f"📝 Причина: {reason}"])
        return "\n".join(lines)


class ModerationService:
    def __init__(self, api: API) -> None:
        self.api = api

    @staticmethod
    def peer_to_chat_id(peer_id: int) -> int:
        return int(peer_id - 2_000_000_000)

    async def kick_from_chat(
        self,
        peer_id: int,
        target_vk_id: int,
    ) -> KickResult:
        if peer_id < 2_000_000_000:
            return KickResult(peer_id=peer_id, success=False, error="Не беседа")
        chat_id = self.peer_to_chat_id(peer_id)
        try:
            await self.api.messages.remove_chat_user(
                chat_id=chat_id,
                member_id=target_vk_id,
            )
            return KickResult(peer_id=peer_id, success=True)
        except Exception as exc:
            logger.warning("kick failed peer=%s target=%s: %s", peer_id, target_vk_id, exc)
            return KickResult(
                peer_id=peer_id,
                success=False,
                error=humanize_kick_error(exc),
            )

    async def kick(
        self,
        *,
        server_id: int,
        pool_id: int | None,
        peer_id: int,
        actor_vk_id: int,
        target_vk_id: int,
        reason: str | None,
    ) -> KickResult:
        result = await self.kick_from_chat(peer_id, target_vk_id)
        await ModerationRepository.log_kick(
            server_id=server_id,
            pool_id=pool_id,
            actor_vk_id=actor_vk_id,
            target_vk_id=target_vk_id,
            action="kick",
            reason=reason,
            peer_id=peer_id,
            success=result.success,
            details=result.error,
        )
        return result

    async def pullkick(
        self,
        *,
        server_id: int,
        pool_id: int,
        actor_vk_id: int,
        target_vk_id: int,
        reason: str | None,
    ) -> PullKickReport:
        chats = await ChatRepository.list_by_pool(pool_id)
        report = PullKickReport(total=len(chats))

        for chat in chats:
            result = await self.kick_from_chat(chat.peer_id, target_vk_id)
            result.title = chat.title or chat.alias or f"peer {chat.peer_id}"
            report.results.append(result)
            if result.success:
                report.kicked += 1
            else:
                report.failed += 1

        await ModerationRepository.log_kick(
            server_id=server_id,
            pool_id=pool_id,
            actor_vk_id=actor_vk_id,
            target_vk_id=target_vk_id,
            action="pullkick",
            reason=reason,
            success=report.kicked > 0,
            details=report.summary(),
        )
        return report
