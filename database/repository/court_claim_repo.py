"""Репозиторий учёта закрытых исков."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from database.models.court_claim import CourtClaimClose
from database.repository.user_repo import UserRepository

MSK = timezone(timedelta(hours=3))
UTC = timezone.utc


def week_start_msk_utc() -> datetime:
    """Понедельник 00:00 МСК → UTC."""
    now = datetime.now(MSK)
    monday = now.date() - timedelta(days=now.weekday())
    return datetime(monday.year, monday.month, monday.day, tzinfo=MSK).astimezone(UTC)


class CourtClaimRepository:
    @staticmethod
    async def record_close(
        thread_id: int,
        *,
        closed_by_vk_id: int,
        server_id: int,
        closed_at: datetime | None = None,
    ) -> bool:
        """Записать закрытие. False если thread_id уже есть (без дублей)."""
        existing = await CourtClaimClose.get_or_none(thread_id=thread_id)
        if existing:
            return False

        forum_id = await UserRepository.get_forum_member_id(closed_by_vk_id)
        when = closed_at or datetime.now(UTC)
        if when.tzinfo is None:
            when = when.replace(tzinfo=UTC)

        await CourtClaimClose.create(
            thread_id=thread_id,
            server_id=server_id,
            closed_by_vk_id=closed_by_vk_id,
            forum_member_id=forum_id,
            closed_at=when,
        )
        return True

    @staticmethod
    async def clear_close(thread_id: int) -> bool:
        """Снять учёт при открытии темы. True если запись удалена."""
        deleted = await CourtClaimClose.filter(thread_id=thread_id).delete()
        return deleted > 0

    @staticmethod
    async def exists(thread_id: int) -> bool:
        return await CourtClaimClose.exists(thread_id=thread_id)

    @staticmethod
    async def count_total(vk_id: int, server_id: int) -> int:
        return await CourtClaimClose.filter(
            closed_by_vk_id=vk_id,
            server_id=server_id,
        ).count()

    @staticmethod
    async def count_week(vk_id: int, server_id: int) -> int:
        since = week_start_msk_utc()
        return await CourtClaimClose.filter(
            closed_by_vk_id=vk_id,
            server_id=server_id,
            closed_at__gte=since,
        ).count()

    @staticmethod
    async def record_close_if_missing(
        thread_id: int,
        *,
        closed_by_vk_id: int,
        server_id: int,
        forum_member_id: str | None = None,
        closed_at: datetime | None = None,
    ) -> bool:
        """Для /claimfill: вставить только если нет записи."""
        if await CourtClaimClose.exists(thread_id=thread_id):
            return False
        when = closed_at or datetime.now(UTC)
        if when.tzinfo is None:
            when = when.replace(tzinfo=UTC)
        member_id = forum_member_id
        if not member_id:
            member_id = await UserRepository.get_forum_member_id(closed_by_vk_id)
        await CourtClaimClose.create(
            thread_id=thread_id,
            server_id=server_id,
            closed_by_vk_id=closed_by_vk_id,
            forum_member_id=member_id,
            closed_at=when,
        )
        return True
