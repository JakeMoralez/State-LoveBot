"""Репозиторий пулов бесед."""

from __future__ import annotations

from database.models.pool import Pool
from database.models.server import Server


class PoolRepository:
    @staticmethod
    async def get_by_id(pool_id: int) -> Pool | None:
        return await Pool.filter(id=pool_id).prefetch_related("server").first()

    @staticmethod
    async def get_by_name(server_id: int, name: str) -> Pool | None:
        return await Pool.get_or_none(server_id=server_id, name=name)

    @staticmethod
    async def list_by_server(server_id: int) -> list[Pool]:
        return await Pool.filter(server_id=server_id).order_by("name")

    @staticmethod
    async def create(
        server_id: int,
        name: str,
        description: str | None = None,
        created_by: int | None = None,
    ) -> Pool:
        server = await Server.get(id=server_id)
        return await Pool.create(
            server=server,
            name=name,
            description=description,
            created_by=created_by,
        )
