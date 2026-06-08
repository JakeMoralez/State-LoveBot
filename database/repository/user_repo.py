"""Репозиторий пользователей и прав доступа."""

from __future__ import annotations

from datetime import datetime, timezone

from config.settings import MAIN_ADMIN_ID
from database.models.server import Server
from database.models.user import AccessLevel, User, UserServerAccess


class UserRepository:
    @staticmethod
    async def is_developer(vk_id: int) -> bool:
        """Разработчик: MAIN_ADMIN_ID из .env или уровень 10 на любом сервере."""
        if MAIN_ADMIN_ID and vk_id == MAIN_ADMIN_ID:
            return True
        return await UserServerAccess.filter(
            user_id=vk_id,
            access_level=AccessLevel.DEVELOPER,
        ).exists()

    @staticmethod
    async def get_effective_level(vk_id: int, server_id: int) -> int:
        return await UserRepository.get_access_level(vk_id, server_id)
    @staticmethod
    async def get_by_vk_id(vk_id: int) -> User | None:
        return await User.get_or_none(vk_id=vk_id)

    @staticmethod
    async def get_by_username(username: str) -> User | None:
        clean = username.lower().lstrip("@")
        return await User.filter(username__iexact=clean).first()

    @staticmethod
    async def get_by_nickname(nickname: str) -> User | None:
        return await User.filter(nickname__iexact=nickname).first()

    @staticmethod
    async def is_registered(vk_id: int) -> bool:
        return await User.filter(vk_id=vk_id).exists()

    @staticmethod
    async def list_server_access(
        server_id: int,
        *,
        min_level: int = 1,
    ) -> list[tuple[User, int]]:
        rows = (
            await UserServerAccess.filter(
                server_id=server_id,
                access_level__gte=min_level,
            )
            .prefetch_related("user")
            .order_by("-access_level", "user_id")
        )
        return [(row.user, row.access_level) for row in rows]

    @staticmethod
    async def get_access_level(vk_id: int, server_id: int) -> int:
        """Эффективный уровень: 10 глобально, иначе уровень на сервере."""
        if await UserRepository.is_developer(vk_id):
            return AccessLevel.DEVELOPER

        access = await UserServerAccess.get_or_none(
            user_id=vk_id,
            server_id=server_id,
        )
        return access.access_level if access else 0

    @staticmethod
    async def set_access_level(
        vk_id: int,
        server_id: int,
        level: int,
        granted_by: int | None = None,
    ) -> UserServerAccess:
        user = await User.get(vk_id=vk_id)
        server = await Server.get(id=server_id)
        access, _ = await UserServerAccess.get_or_create(
            user=user,
            server=server,
            defaults={"access_level": level, "granted_by": granted_by},
        )
        access.access_level = level
        access.granted_by = granted_by
        await access.save()
        return access

    @staticmethod
    async def set_nickname(vk_id: int, nickname: str) -> User:
        user = await User.get(vk_id=vk_id)
        user.nickname = nickname
        user.last_used = datetime.now(timezone.utc)
        await user.save()
        return user

    @staticmethod
    async def ensure_user(
        vk_id: int,
        username: str | None = None,
        added_by: int | None = None,
    ) -> User:
        user, created = await User.get_or_create(
            vk_id=vk_id,
            defaults={"username": username, "added_by": added_by},
        )
        if username and user.username != username:
            user.username = username
            await user.save()
        return user

    @staticmethod
    async def get_user_pools_info(vk_id: int, server_id: int) -> list[str]:
        """Пулы, в беседах которых состоит пользователь (по зарегистрированным чатам)."""
        from database.models.chat import Chat
        from database.models.pool import Pool

        pools = await Pool.filter(server_id=server_id).prefetch_related("chats")
        result: list[str] = []
        for pool in pools:
            for chat in pool.chats:
                # Упрощённо: пользователь «в пуле», если есть доступ на сервере
                if await UserRepository.get_access_level(vk_id, server_id) > 0:
                    if pool.name not in result:
                        result.append(pool.name)
                    break
        return result
