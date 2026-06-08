"""Настройки беседы и учёт добровольных выходов."""

from __future__ import annotations

from database.models.chat_settings import ChatLeftMember, ChatPeerSettings, GuardMode


class ChatSettingsRepository:
    @staticmethod
    def normalize_mode(raw: str, *, allow_ask: bool = True) -> str | None:
        value = (raw or "").strip().lower()
        allowed = GuardMode.ALL if allow_ask else (GuardMode.OFF, GuardMode.ON)
        if value in allowed:
            return value
        if value in ("вкл", "да", "yes", "1", "true"):
            return GuardMode.ON
        if value in ("выкл", "нет", "no", "0", "false"):
            return GuardMode.OFF
        if allow_ask and value in ("спросить", "?"):
            return GuardMode.ASK
        return None

    @staticmethod
    async def get(peer_id: int) -> ChatPeerSettings:
        settings, _ = await ChatPeerSettings.get_or_create(peer_id=peer_id)
        return settings

    @staticmethod
    async def set_mode(
        peer_id: int,
        field: str,
        mode: str,
        *,
        updated_by: int | None = None,
        allow_ask: bool = True,
    ) -> ChatPeerSettings:
        allowed = GuardMode.ALL if allow_ask else (GuardMode.OFF, GuardMode.ON)
        if mode not in allowed:
            raise ValueError("Недопустимый режим")
        settings = await ChatSettingsRepository.get(peer_id)
        setattr(settings, field, mode)
        settings.updated_by = updated_by
        await settings.save()
        return settings

    @staticmethod
    async def record_voluntary_leave(peer_id: int, user_id: int) -> None:
        await ChatLeftMember.update_or_create(
            peer_id=peer_id,
            user_id=user_id,
            defaults={},
        )

    @staticmethod
    async def clear_left_record(peer_id: int, user_id: int) -> None:
        await ChatLeftMember.filter(peer_id=peer_id, user_id=user_id).delete()

    @staticmethod
    async def was_voluntary_leave(peer_id: int, user_id: int) -> bool:
        return await ChatLeftMember.filter(
            peer_id=peer_id,
            user_id=user_id,
        ).exists()

    @staticmethod
    def mode_label(mode: str) -> str:
        return {
            GuardMode.OFF: "выкл",
            GuardMode.ON: "вкл",
            GuardMode.ASK: "спрашивать",
        }.get(mode, mode)
