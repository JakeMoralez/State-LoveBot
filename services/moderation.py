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
    gos_included: int = 0
    all_chats: bool = False
    scope_label: str | None = None
    results: list[KickResult] = field(default_factory=list)

    def summary(self) -> str:
        if self.scope_label:
            return f"Исключён из {self.kicked}/{self.total} ({self.scope_label})."
        if self.all_chats:
            return f"Исключён из {self.kicked}/{self.total} бесед сервера."
        if self.gos_included:
            return (
                f"Исключён из {self.kicked}/{self.total} бесед "
                f"(пул + {self.gos_included} gos)."
            )
        return f"Исключён из {self.kicked}/{self.total} бесед пула."

    def _scope_label(self, pool_name: str) -> str:
        if self.scope_label:
            return self.scope_label
        if self.all_chats:
            return "сервера (все зарегистрированные)"
        if self.gos_included:
            return f"«{pool_name}» + gos ({self.gos_included})"
        return f"«{pool_name}»"

    def format_message(
        self,
        *,
        target_label: str,
        pool_name: str,
        reason: str | None = None,
    ) -> str:
        scope_label = self._scope_label(pool_name)
        if self.total == 0:
            if self.scope_label:
                return f"❌ Нет бесед для исключения ({self.scope_label})."
            if self.all_chats:
                return "❌ На сервере нет зарегистрированных бесед."
            return "❌ В пуле нет зарегистрированных бесед."

        if self.kicked == self.total:
            header = (
                f"✅ | {target_label} был(а) исключён(а) "
                f"из всех конференций {scope_label}!"
            )
        elif self.kicked > 0:
            header = (
                f"⚠️ | {target_label} исключён(а) "
                f"из {self.kicked}/{self.total} конференций {scope_label}"
            )
        else:
            header = (
                f"❌ | Не удалось исключить {target_label} "
                f"из конференций {scope_label}"
            )

        lines = [header, "", "📂 Список конференций:"]
        for item in self.results:
            name = item.title or f"Беседа {item.peer_id}"
            if item.success:
                lines.append(f"• {name} — Исключён ✅")
            else:
                err = item.error or "Нет прав у бота"
                lines.append(f"• {name} — {err} ❌")

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

    async def pullkick_peers(
        self,
        *,
        server_id: int,
        pool_id: int | None,
        actor_vk_id: int,
        target_vk_id: int,
        reason: str | None,
        peers: list[tuple[int, str]],
        scope_label: str = "",
    ) -> PullKickReport:
        """Кик по явному списку (peer_id, title)."""
        report = PullKickReport(
            total=len(peers),
            all_chats=False,
            scope_label=scope_label or None,
        )

        for peer_id, title in peers:
            result = await self.kick_from_chat(peer_id, target_vk_id)
            result.title = title or f"peer {peer_id}"
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

    async def pullkick(
        self,
        *,
        server_id: int,
        pool_id: int | None,
        actor_vk_id: int,
        target_vk_id: int,
        reason: str | None,
        all_chats: bool = False,
    ) -> PullKickReport:
        if all_chats:
            chats = await ChatRepository.list_all_registered(server_id)
            report = PullKickReport(total=len(chats), all_chats=True)
        else:
            if pool_id is None:
                return PullKickReport(total=0)
            chats, gos_included = await ChatRepository.list_for_pullkick(
                server_id,
                pool_id,
            )
            report = PullKickReport(total=len(chats), gos_included=gos_included)

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
            action="pullkick_all" if all_chats else "pullkick",
            reason=reason,
            success=report.kicked > 0,
            details=report.summary(),
        )
        return report
