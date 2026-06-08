"""Репозиторий серверов."""

from __future__ import annotations

from database.models.server import Server


class ServerRepository:
    @staticmethod
    async def get_by_id(server_id: int) -> Server | None:
        return await Server.get_or_none(id=server_id)

    @staticmethod
    async def get_by_slug(slug: str) -> Server | None:
        return await Server.get_or_none(slug=slug)

    @staticmethod
    async def get_or_create_default(slug: str, name: str) -> Server:
        server, _ = await Server.get_or_create(
            slug=slug,
            defaults={"name": name},
        )
        if server.name != name:
            server.name = name
            await server.save()
        return server

    @staticmethod
    async def list_active() -> list[Server]:
        return await Server.filter(is_active=True).order_by("id")
