"""Форумные роли — отдельно от числовых уровней доступа (1–10)."""

from __future__ import annotations

from datetime import datetime, timezone

from database.models.role_chat import ForumRoleKey, RoleChat
from database.models.server import Server
from database.models.user import User
from database.repository.user_repo import UserRepository


class ForumRoleRepository:
    @staticmethod
    async def is_judge(vk_id: int) -> bool:
        user = await User.get_or_none(vk_id=vk_id)
        return bool(user and user.is_judge)

    @staticmethod
    async def is_attorney(vk_id: int) -> bool:
        user = await User.get_or_none(vk_id=vk_id)
        return bool(user and user.is_attorney)

    @staticmethod
    async def is_leader(vk_id: int) -> bool:
        user = await User.get_or_none(vk_id=vk_id)
        return bool(user and user.is_leader)

    @staticmethod
    async def has_forum_role(vk_id: int) -> bool:
        user = await User.get_or_none(vk_id=vk_id)
        if not user:
            return False
        return user.is_judge or user.is_attorney or user.is_leader

    @staticmethod
    async def can_use_forum_bot(vk_id: int) -> bool:
        """Доступ к боту: форумная роль или числовой уровень на любом сервере."""
        if await UserRepository.is_developer(vk_id):
            return True
        if await ForumRoleRepository.has_forum_role(vk_id):
            return True
        if await UserRepository.is_registered(vk_id):
            from database.models.user import UserServerAccess

            if await UserServerAccess.filter(user_id=vk_id).exists():
                return True
        return False

    @staticmethod
    async def set_role(
        vk_id: int,
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
        if is_judge:
            if not user.is_judge:
                user.last_used = datetime.now(timezone.utc)
            user.is_judge = True
        if is_attorney:
            user.is_attorney = True
        if is_leader:
            user.is_leader = True
        if is_admin:
            user.is_admin = True
        await user.save()
        return user

    @staticmethod
    async def clear_judge_role(vk_id: int) -> bool:
        user = await User.get_or_none(vk_id=vk_id)
        if not user or not user.is_judge:
            return False
        user.is_judge = False
        await user.save()
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
    async def list_by_role(role: str) -> list[User]:
        if role == ForumRoleKey.ADMIN:
            return await User.filter(is_admin=True).order_by("-added_at")
        field_map = {
            ForumRoleKey.JUDGE: "is_judge",
            ForumRoleKey.ATTORNEY: "is_attorney",
            ForumRoleKey.LEADER: "is_leader",
        }
        field = field_map.get(role)
        if not field:
            return []
        return await User.filter(**{field: True}).order_by("-added_at")

    @staticmethod
    async def save_role_chat(
        role: str,
        peer_id: int,
        registered_by: int,
        server_id: int | None = None,
    ) -> RoleChat:
        server = await Server.get(id=server_id) if server_id else None
        chat, _ = await RoleChat.get_or_create(
            role=role,
            defaults={
                "peer_id": peer_id,
                "registered_by": registered_by,
                "server": server,
            },
        )
        chat.peer_id = peer_id
        chat.registered_by = registered_by
        chat.server = server
        await chat.save()
        return chat

    @staticmethod
    async def get_role_chat(role: str) -> int | None:
        chat = await RoleChat.get_or_none(role=role)
        return chat.peer_id if chat else None

    @staticmethod
    async def find_role_by_peer(peer_id: int) -> str | None:
        chat = await RoleChat.get_or_none(peer_id=peer_id)
        return chat.role if chat else None

    @staticmethod
    async def revoke_role_on_leave(vk_id: int, role: str) -> bool:
        """Снимает одну форумную роль при выходе из привязанной беседы."""
        user = await User.get_or_none(vk_id=vk_id)
        if not user:
            return False
        field_map = {
            ForumRoleKey.JUDGE: "is_judge",
            ForumRoleKey.ATTORNEY: "is_attorney",
            ForumRoleKey.LEADER: "is_leader",
            ForumRoleKey.ADMIN: "is_admin",
        }
        field = field_map.get(role)
        if not field or not getattr(user, field, False):
            return False
        setattr(user, field, False)
        await user.save()
        return True

    @staticmethod
    async def delete_role_chat(role: str) -> bool:
        deleted = await RoleChat.filter(role=role).delete()
        return deleted > 0

    @staticmethod
    async def clear_all_forum_roles(vk_id: int) -> None:
        user = await User.get_or_none(vk_id=vk_id)
        if not user:
            return
        user.is_judge = False
        user.is_attorney = False
        user.is_leader = False
        user.is_admin = False
        await user.save()
