"""Репозиторий логов модерации."""

from __future__ import annotations

from database.models.moderation import ModerationLog
from database.models.pool import Pool
from database.models.server import Server


class ModerationRepository:
    @staticmethod
    async def log_kick(
        server_id: int,
        actor_vk_id: int,
        target_vk_id: int,
        action: str,
        reason: str | None,
        peer_id: int | None = None,
        pool_id: int | None = None,
        success: bool = True,
        details: str | None = None,
    ) -> ModerationLog:
        server = await Server.get(id=server_id)
        pool = await Pool.get(id=pool_id) if pool_id else None
        return await ModerationLog.create(
            server=server,
            pool=pool,
            actor_vk_id=actor_vk_id,
            target_vk_id=target_vk_id,
            action=action,
            reason=reason,
            peer_id=peer_id,
            success=success,
            details=details,
        )
