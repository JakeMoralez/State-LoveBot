"""Конгресс: беседа + спикер / вице-спикер (setnick только в конференции)."""

from __future__ import annotations

from database.models.role_chat import ForumRoleKey
from database.models.user import User
from database.repository.chat_repo import ChatRepository
from database.repository.forum_role_repo import ForumRoleRepository
from database.repository.user_repo import UserRepository

CONGRESS_DEFAULT_ALIAS = "congress"


class CongressRepository:
    @staticmethod
    async def get_congress_peer_id() -> int | None:
        return await ForumRoleRepository.get_role_chat(ForumRoleKey.CONGRESS)

    @staticmethod
    async def is_congress_chat(peer_id: int) -> bool:
        congress_peer = await CongressRepository.get_congress_peer_id()
        return congress_peer is not None and peer_id == congress_peer

    @staticmethod
    async def is_officer(vk_id: int) -> bool:
        user = await User.get_or_none(vk_id=vk_id)
        if not user:
            return False
        return user.is_congress_speaker or user.is_congress_vice

    @staticmethod
    async def _officer_in_congress(peer_id: int, vk_id: int) -> bool:
        if not await CongressRepository.is_congress_chat(peer_id):
            return False
        if await UserRepository.is_developer(vk_id):
            return True
        return await CongressRepository.is_officer(vk_id)

    @staticmethod
    async def can_setnick_in_chat(peer_id: int, vk_id: int) -> bool:
        return await CongressRepository._officer_in_congress(peer_id, vk_id)

    @staticmethod
    async def can_kick_in_chat(peer_id: int, vk_id: int) -> bool:
        return await CongressRepository._officer_in_congress(peer_id, vk_id)

    @staticmethod
    async def can_use_msg(peer_id: int, vk_id: int) -> bool:
        if not await CongressRepository.is_officer(vk_id):
            if await UserRepository.is_developer(vk_id):
                return await CongressRepository.is_congress_chat(peer_id)
            return False
        if peer_id < 2_000_000_000:
            return True
        return await CongressRepository.is_congress_chat(peer_id)

    @staticmethod
    async def get_congress_alias(server_id: int) -> str | None:
        peer_id = await CongressRepository.get_congress_peer_id()
        if not peer_id:
            return None
        chat = await ChatRepository.get_by_peer_id(peer_id)
        if chat and chat.server_id != server_id:
            return None
        if chat and chat.alias:
            return chat.alias
        return CONGRESS_DEFAULT_ALIAS

    @staticmethod
    async def register_chat(
        peer_id: int,
        registered_by: int,
        server_id: int,
        *,
        alias: str | None = None,
        title: str | None = None,
    ) -> str:
        await ForumRoleRepository.save_role_chat(
            ForumRoleKey.CONGRESS,
            peer_id,
            registered_by,
            server_id,
        )

        normalized = CONGRESS_DEFAULT_ALIAS
        if alias:
            ok, result = ChatRepository.validate_alias(alias)
            if not ok:
                raise ValueError(result)
            normalized = result

        existing = await ChatRepository.get_by_alias(server_id, normalized)
        if existing and existing.peer_id != peer_id:
            raise ValueError(f"Алиас «{normalized}» уже занят другой беседой.")

        await ChatRepository.register_chat(
            peer_id=peer_id,
            server_id=server_id,
            pool_id=None,
            alias=normalized,
            title=title,
            registered_by=registered_by,
        )
        return normalized

    @staticmethod
    async def _clear_role(role_field: str) -> None:
        await User.filter(**{role_field: True}).update(**{role_field: False})

    @staticmethod
    async def set_speaker(
        vk_id: int,
        *,
        username: str | None,
        assigned_by: int,
    ) -> User:
        await CongressRepository._clear_role("is_congress_speaker")
        user = await UserRepository.ensure_user(vk_id, username, assigned_by)
        user.is_congress_speaker = True
        await user.save()
        return user

    @staticmethod
    async def set_vice(
        vk_id: int,
        *,
        username: str | None,
        assigned_by: int,
    ) -> User:
        await CongressRepository._clear_role("is_congress_vice")
        user = await UserRepository.ensure_user(vk_id, username, assigned_by)
        user.is_congress_vice = True
        await user.save()
        return user

    @staticmethod
    async def clear_speaker() -> bool:
        updated = await User.filter(is_congress_speaker=True).update(
            is_congress_speaker=False
        )
        return updated > 0

    @staticmethod
    async def clear_vice() -> bool:
        updated = await User.filter(is_congress_vice=True).update(
            is_congress_vice=False
        )
        return updated > 0

    @staticmethod
    async def clear_speaker_for(vk_id: int) -> bool:
        user = await User.get_or_none(vk_id=vk_id)
        if not user or not user.is_congress_speaker:
            return False
        user.is_congress_speaker = False
        await user.save()
        return True

    @staticmethod
    async def clear_vice_for(vk_id: int) -> bool:
        user = await User.get_or_none(vk_id=vk_id)
        if not user or not user.is_congress_vice:
            return False
        user.is_congress_vice = False
        await user.save()
        return True

    @staticmethod
    async def get_speaker() -> User | None:
        return await User.filter(is_congress_speaker=True).first()

    @staticmethod
    async def get_vice() -> User | None:
        return await User.filter(is_congress_vice=True).first()

    @staticmethod
    async def revoke_officer_on_leave(peer_id: int, vk_id: int) -> str | None:
        """Снять спикера/вице при выходе из беседы конгресса."""
        if not await CongressRepository.is_congress_chat(peer_id):
            return None
        user = await User.get_or_none(vk_id=vk_id)
        if not user:
            return None
        if user.is_congress_speaker:
            user.is_congress_speaker = False
            await user.save()
            return "speaker"
        if user.is_congress_vice:
            user.is_congress_vice = False
            await user.save()
            return "vice"
        return None
