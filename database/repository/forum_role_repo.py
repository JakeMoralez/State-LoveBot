"""Форумные роли — отдельно от числовых уровней, привязаны к server_id."""

from __future__ import annotations

from datetime import datetime, timezone

from tortoise.expressions import Q

from config.settings import DEFAULT_SERVER_ID
from database.models.role_chat import ForumRoleKey, RoleChat
from database.models.server import Server
from database.models.user import User, UserServerAccess
from database.repository.user_repo import UserRepository

_ROLE_FIELDS = {
    ForumRoleKey.JUDGE: "is_judge",
    ForumRoleKey.ATTORNEY: "is_attorney",
    ForumRoleKey.LEADER: "is_leader",
}


class ForumRoleRepository:
    @staticmethod
    async def _get_access(vk_id: int, server_id: int) -> UserServerAccess | None:
        return await UserServerAccess.get_or_none(
            user_id=vk_id,
            server_id=server_id,
        )

    @staticmethod
    async def _ensure_access(
        vk_id: int,
        server_id: int,
        *,
        username: str | None = None,
        added_by: int | None = None,
    ) -> UserServerAccess:
        user = await UserRepository.ensure_user(vk_id, username, added_by)
        server = await Server.get(id=server_id)
        access, _ = await UserServerAccess.get_or_create(
            user=user,
            server=server,
            defaults={"access_level": 0},
        )
        return access

    @staticmethod
    async def is_judge(vk_id: int, server_id: int) -> bool:
        access = await ForumRoleRepository._get_access(vk_id, server_id)
        return bool(access and access.is_judge)

    @staticmethod
    async def is_judge_effective(vk_id: int, server_id: int) -> bool:
        """Судья на сервере чата, в ЦА (DEFAULT_SERVER_ID) или legacy users.is_judge."""
        if await ForumRoleRepository.is_judge(vk_id, server_id):
            return True
        if server_id != DEFAULT_SERVER_ID:
            if await ForumRoleRepository.is_judge(vk_id, DEFAULT_SERVER_ID):
                return True
        user = await User.get_or_none(vk_id=vk_id)
        return bool(user and user.is_judge)

    @staticmethod
    async def is_attorney(vk_id: int, server_id: int) -> bool:
        access = await ForumRoleRepository._get_access(vk_id, server_id)
        return bool(access and access.is_attorney)

    @staticmethod
    async def is_leader(vk_id: int, server_id: int) -> bool:
        access = await ForumRoleRepository._get_access(vk_id, server_id)
        return bool(access and access.is_leader)

    @staticmethod
    async def has_forum_role(vk_id: int, server_id: int | None = None) -> bool:
        qs = UserServerAccess.filter(user_id=vk_id)
        if server_id is not None:
            qs = qs.filter(server_id=server_id)
        return await qs.filter(
            Q(is_judge=True)
            | Q(is_attorney=True)
            | Q(is_leader=True)
        ).exists()

    @staticmethod
    async def can_use_forum_bot(vk_id: int) -> bool:
        """Доступ к боту: разработчик, роль на любом сервере или числовой уровень."""
        if await UserRepository.is_developer(vk_id):
            return True
        if await ForumRoleRepository.has_forum_role(vk_id):
            return True
        if await UserRepository.is_registered(vk_id):
            if await UserServerAccess.filter(user_id=vk_id).exists():
                return True
        return False

    @staticmethod
    async def set_role(
        vk_id: int,
        server_id: int,
        *,
        username: str | None,
        added_by: int,
        note: str = "",
        is_judge: bool = False,
        is_attorney: bool = False,
        is_leader: bool = False,
        is_admin: bool = False,
    ) -> User:
        user = await UserRepository.ensure_user(vk_id, username, added_by)
        if note:
            user.note = note
        if is_admin:
            user.is_admin = True
            await user.save()

        access = await ForumRoleRepository._ensure_access(
            vk_id,
            server_id,
            username=username,
            added_by=added_by,
        )
        now = datetime.now(timezone.utc)
        if is_judge:
            access.is_judge = True
            user.last_used = now
        if is_attorney:
            access.is_attorney = True
        if is_leader:
            access.is_leader = True
        await access.save()
        await user.save()
        return user

    @staticmethod
    async def clear_judge_role(vk_id: int, server_id: int) -> bool:
        access = await ForumRoleRepository._get_access(vk_id, server_id)
        if not access or not access.is_judge:
            return False
        access.is_judge = False
        await access.save()
        return True

    @staticmethod
    async def clear_leader_role(vk_id: int, server_id: int) -> bool:
        access = await ForumRoleRepository._get_access(vk_id, server_id)
        if not access or not access.is_leader:
            return False
        access.is_leader = False
        await access.save()
        return True

    @staticmethod
    async def remove_user(vk_id: int) -> bool:
        deleted = await User.filter(vk_id=vk_id).delete()
        return deleted > 0

    @staticmethod
    async def remove_user_by_username(username: str) -> bool:
        user = await UserRepository.get_by_username(username)
        if not user:
            return False
        await user.delete()
        return True

    @staticmethod
    async def set_note(vk_id: int, note: str) -> None:
        user = await User.get(vk_id=vk_id)
        user.note = note
        await user.save()

    @staticmethod
    async def list_by_role(role: str, server_id: int) -> list[User]:
        if role == ForumRoleKey.ADMIN:
            return await User.filter(is_admin=True).order_by("-added_at")

        field = _ROLE_FIELDS.get(role)
        if not field:
            return []

        rows = (
            await UserServerAccess.filter(server_id=server_id, **{field: True})
            .prefetch_related("user")
            .order_by("-granted_at")
        )
        return [row.user for row in rows]

    @staticmethod
    async def save_role_chat(
        role: str,
        peer_id: int,
        registered_by: int,
        server_id: int,
    ) -> RoleChat:
        server = await Server.get(id=server_id)
        chat, _ = await RoleChat.get_or_create(
            server=server,
            role=role,
            defaults={
                "peer_id": peer_id,
                "registered_by": registered_by,
            },
        )
        chat.peer_id = peer_id
        chat.registered_by = registered_by
        await chat.save()
        return chat

    @staticmethod
    async def get_role_chat(role: str, server_id: int) -> int | None:
        chat = await RoleChat.get_or_none(server_id=server_id, role=role)
        return chat.peer_id if chat else None

    @staticmethod
    async def get_role_chat_by_peer(peer_id: int) -> RoleChat | None:
        return await RoleChat.get_or_none(peer_id=peer_id)

    @staticmethod
    async def find_role_by_peer(peer_id: int) -> str | None:
        chat = await RoleChat.get_or_none(peer_id=peer_id)
        return chat.role if chat else None

    @staticmethod
    async def revoke_role_on_leave(
        vk_id: int,
        role: str,
        server_id: int,
    ) -> bool:
        field = _ROLE_FIELDS.get(role)
        if role == ForumRoleKey.ADMIN:
            user = await User.get_or_none(vk_id=vk_id)
            if not user or not user.is_admin:
                return False
            user.is_admin = False
            await user.save()
            return True
        if not field:
            return False
        access = await ForumRoleRepository._get_access(vk_id, server_id)
        if not access or not getattr(access, field, False):
            return False
        setattr(access, field, False)
        await access.save()
        return True

    @staticmethod
    async def delete_role_chat(role: str, server_id: int) -> bool:
        deleted = await RoleChat.filter(server_id=server_id, role=role).delete()
        return deleted > 0

    @staticmethod
    async def clear_all_forum_roles(vk_id: int, server_id: int) -> None:
        access = await ForumRoleRepository._get_access(vk_id, server_id)
        if not access:
            return
        access.is_judge = False
        access.is_attorney = False
        access.is_leader = False
        await access.save()
