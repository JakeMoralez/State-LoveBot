"""Репозиторий серверов."""

from __future__ import annotations

from config.settings import DEFAULT_SERVER_ID
from database.models.chat import Chat
from database.models.moderation import ModerationLog
from database.models.pool import Pool
from database.models.role_chat import RoleChat
from database.models.server import Server
from database.models.user import UserServerAccess


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

    @staticmethod
    async def get_judge_forum_id(server_id: int) -> int | None:
        server = await Server.get_or_none(id=server_id)
        if server and server.judge_forum_id:
            return int(server.judge_forum_id)
        return None

    @staticmethod
    async def update_settings(
        server_id: int,
        *,
        tag: str | None = None,
        name: str | None = None,
        judge_forum_id: int | None = None,
        clear_judge_forum: bool = False,
    ) -> Server:
        server = await ServerRepository.get_or_create_by_id(server_id)
        if tag is not None:
            cleaned = tag.strip()
            server.tag = cleaned or None
        if name is not None:
            cleaned = name.strip()
            if cleaned:
                server.name = cleaned
        if clear_judge_forum:
            server.judge_forum_id = None
        elif judge_forum_id is not None:
            server.judge_forum_id = judge_forum_id
        await server.save()
        return server

    @staticmethod
    async def merge_user_server_access(old_id: int, new_id: int) -> int:
        """Слияние доступов old_id → new_id (без дубликата user_id)."""
        if old_id == new_id:
            return 0

        merged = 0
        bool_fields = (
            "has_ca_access",
            "is_judge",
            "is_attorney",
            "is_leader",
            "is_congress_speaker",
            "is_congress_vice",
        )
        old_rows = await UserServerAccess.filter(server_id=old_id)
        for old_acc in old_rows:
            target = await UserServerAccess.get_or_none(
                user_id=old_acc.user_id,
                server_id=new_id,
            )
            if not target:
                old_acc.server_id = new_id
                await old_acc.save()
                merged += 1
                continue

            if old_acc.access_level > target.access_level:
                target.access_level = old_acc.access_level
            if old_acc.nickname and not target.nickname:
                target.nickname = old_acc.nickname
            for field in bool_fields:
                if getattr(old_acc, field, False):
                    setattr(target, field, True)
            if old_acc.ca_auto_peer_id and not target.ca_auto_peer_id:
                target.ca_auto_peer_id = old_acc.ca_auto_peer_id
            if old_acc.granted_by and not target.granted_by:
                target.granted_by = old_acc.granted_by
            await target.save()
            await old_acc.delete()
            merged += 1
        return merged

    @staticmethod
    async def remap_role_chats(old_id: int, new_id: int) -> None:
        if old_id == new_id:
            return
        for chat in await RoleChat.filter(server_id=old_id):
            existing = await RoleChat.get_or_none(server_id=new_id, role=chat.role)
            if existing:
                await chat.delete()
            else:
                chat.server_id = new_id
                await chat.save()

    @staticmethod
    async def remap_server_references(old_id: int, new_id: int) -> None:
        if old_id == new_id:
            return
        await ServerRepository.merge_user_server_access(old_id, new_id)
        await Chat.filter(server_id=old_id).update(server_id=new_id)
        await Pool.filter(server_id=old_id).update(server_id=new_id)
        await ModerationLog.filter(server_id=old_id).update(server_id=new_id)
        await ServerRepository.remap_role_chats(old_id, new_id)

    @staticmethod
    async def get_or_create_by_id(server_id: int, *, name: str | None = None) -> Server:
        server = await Server.get_or_none(id=server_id)
        if server:
            if name and server.name != name:
                server.name = name
                await server.save()
            return server

        slug = f"s{server_id}"
        display_name = name or f"Arizona №{server_id}"
        return await Server.create(
            id=server_id,
            slug=slug,
            name=display_name,
        )

    @staticmethod
    async def ensure_primary_server(
        server_id: int,
        slug: str,
        name: str,
    ) -> Server:
        by_slug = await Server.get_or_none(slug=slug)
        target = await Server.get_or_none(id=server_id)

        if by_slug and by_slug.id == server_id:
            if by_slug.name != name:
                by_slug.name = name
                await by_slug.save()
            return by_slug

        if by_slug and by_slug.id != server_id:
            old_id = by_slug.id
            if not target:
                target = await Server.create(
                    id=server_id,
                    slug=f"_migrate_{old_id}",
                    name=name,
                    log_peer_id=by_slug.log_peer_id,
                    is_active=by_slug.is_active,
                )
            else:
                if by_slug.log_peer_id and not target.log_peer_id:
                    target.log_peer_id = by_slug.log_peer_id
                target.name = name
                await target.save()

            await ServerRepository.remap_server_references(old_id, server_id)
            by_slug.slug = f"legacy-{old_id}"
            await by_slug.save()
            await by_slug.delete()

            target.slug = slug
            target.name = name
            await target.save()
            return target

        if target:
            target.slug = slug
            target.name = name
            await target.save()
            return target

        return await Server.create(
            id=server_id,
            slug=slug,
            name=name,
        )
