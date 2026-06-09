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

    @staticmethod
    async def set_log_peer(server_id: int, peer_id: int | None) -> Server:
        server = await Server.get(id=server_id)
        server.log_peer_id = peer_id
        await server.save()
        return server

    @staticmethod
    async def get_log_peer_id(server_id: int) -> int | None:
        server = await Server.get_or_none(id=server_id)
        if not server or not server.log_peer_id:
            return None
        return int(server.log_peer_id)
