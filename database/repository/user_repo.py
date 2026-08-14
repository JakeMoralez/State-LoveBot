"""Репозиторий пользователей и прав доступа."""

from __future__ import annotations

from datetime import datetime, timezone

from config.settings import MAIN_ADMIN_ID
from database.models.server import Server
from database.models.user import AccessLevel, User, UserServerAccess
from database.spheres import CENTRAL_APPARATUS
from services.panel_db import read_staff_spheres


class UserRepository:
    @staticmethod
    async def is_developer(vk_id: int) -> bool:
        """Разработчик: MAIN_ADMIN_ID из .env или уровень DEVELOPER на любом сервере."""
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
    async def get_forum_member_id(vk_id: int) -> str | None:
        from services.forum_account import parse_forum_member_id

        user = await User.get_or_none(vk_id=vk_id)
        if not user:
            return None
        return parse_forum_member_id(user.username)

    @staticmethod
    async def set_forum_member_id(vk_id: int, member_id: str | None) -> None:
        user, _ = await User.get_or_create(
            vk_id=vk_id,
            defaults={"username": str(vk_id)},
        )
        user.username = member_id if member_id else str(vk_id)
        user.last_used = datetime.now(timezone.utc)
        await user.save()

    @staticmethod
    async def get_by_username(username: str) -> User | None:
        clean = username.lower().lstrip("@")
        return await User.filter(username__iexact=clean).first()

    @staticmethod
    async def get_by_nickname(nickname: str, server_id: int) -> User | None:
        access = await UserServerAccess.filter(
            server_id=server_id,
            nickname__iexact=nickname,
        ).prefetch_related("user").first()
        return access.user if access else None

    @staticmethod
    async def search_users(
        query: str,
        server_id: int,
        *,
        limit: int = 10,
    ) -> list[User]:
        q = (query or "").strip().lstrip("@")
        if not q:
            return []
        if q.isdigit():
            user = await User.get_or_none(vk_id=int(q))
            return [user] if user else []

        from tortoise.expressions import Q

        seen: set[int] = set()
        result: list[User] = []

        nick_rows = (
            await UserServerAccess.filter(
                server_id=server_id,
                nickname__icontains=q,
            )
            .prefetch_related("user")
            .limit(limit)
        )
        for row in nick_rows:
            if row.user_id not in seen:
                seen.add(row.user_id)
                result.append(row.user)

        if len(result) < limit:
            username_rows = await User.filter(username__icontains=q).limit(limit)
            for user in username_rows:
                if user.vk_id not in seen:
                    seen.add(user.vk_id)
                    result.append(user)
                if len(result) >= limit:
                    break

        return result[:limit]

    @staticmethod
    async def is_registered(vk_id: int) -> bool:
        return await User.filter(vk_id=vk_id).exists()

    @staticmethod
    async def is_pingable_in_chat(vk_id: int, server_id: int) -> bool:
        """7+ ур. не пингуются в /msg и /members; разработчик (DEVELOPER) — исключение."""
        level = await UserRepository.get_access_level(vk_id, server_id)
        if level == AccessLevel.DEVELOPER:
            return True
        return level < AccessLevel.CURATOR

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
    async def list_staff(
        server_id: int,
    ) -> list[tuple[User, int, UserServerAccess | None]]:
        """Все с ур. 1+, доступом ЦА или форумной/конгресс-ролью."""
        from tortoise.expressions import Q

        by_id: dict[int, tuple[User, int, UserServerAccess | None]] = {}

        rows = await UserServerAccess.filter(server_id=server_id).prefetch_related(
            "user"
        )
        for row in rows:
            if row.access_level >= AccessLevel.PGS or row.has_ca_access:
                by_id[row.user_id] = (row.user, row.access_level, row)

        role_q = (
            Q(is_judge=True)
            | Q(is_congress_speaker=True)
            | Q(is_congress_vice=True)
            | Q(is_attorney=True)
            | Q(is_leader=True)
        )
        for row in await UserServerAccess.filter(
            server_id=server_id,
        ).filter(role_q).prefetch_related("user"):
            if row.user_id in by_id:
                continue
            by_id[row.user_id] = (row.user, row.access_level, row)

        for user in await User.filter(is_admin=True):
            if user.vk_id in by_id:
                continue
            acc = await UserServerAccess.get_or_none(
                user_id=user.vk_id, server_id=server_id
            )
            level = acc.access_level if acc else 0
            by_id[user.vk_id] = (user, level, acc)

        result = list(by_id.values())
        result.sort(key=lambda item: (-item[1], item[0].vk_id))
        return result

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
    async def get_server_access(vk_id: int, server_id: int) -> UserServerAccess | None:
        return await UserServerAccess.get_or_none(user_id=vk_id, server_id=server_id)

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
    async def has_ca_access(vk_id: int, server_id: int) -> bool:
        access = await UserServerAccess.get_or_none(user_id=vk_id, server_id=server_id)
        return bool(access and access.has_ca_access)

    @staticmethod
    async def set_ca_access(
        vk_id: int,
        server_id: int,
        *,
        enabled: bool,
        granted_by: int | None = None,
    ) -> UserServerAccess:
        user = await User.get(vk_id=vk_id)
        server = await Server.get(id=server_id)
        access, _ = await UserServerAccess.get_or_create(
            user=user,
            server=server,
            defaults={"access_level": 0, "granted_by": granted_by},
        )
        access.has_ca_access = enabled
        await access.save()
        return access

    @staticmethod
    async def can_use_ca_scope(vk_id: int, server_id: int) -> bool:
        """ЗГС+ (3+), ур. 5+ или флаг has_ca_access — доступ к общим беседам следящих."""
        if await UserRepository.is_developer(vk_id):
            return True
        level = await UserRepository.get_access_level(vk_id, server_id)
        if level >= AccessLevel.ZGS:
            return True
        return await UserRepository.has_ca_access(vk_id, server_id)

    @staticmethod
    async def _sled_ca_leave_preserves_access(
        access: UserServerAccess,
        spheres: list[str],
    ) -> bool:
        """Не снимать уровень/ЦА, если есть официальное назначение или вторая сфера."""
        level = access.access_level
        if level >= AccessLevel.ZGS_GOS:
            return True
        if level > AccessLevel.PGS:
            return True
        if access.granted_by is not None and access.granted_by > 0:
            return True
        non_ca = [s for s in spheres if s != CENTRAL_APPARATUS]
        if len(non_ca) > 0:
            return True
        if len(spheres) > 1:
            return True
        return False

    @staticmethod
    async def can_use_portal(vk_id: int, server_id: int) -> bool:
        """Вход на портал State Love: уровень ПГС (1) и выше."""
        if await UserRepository.is_developer(vk_id):
            return True
        level = await UserRepository.get_access_level(vk_id, server_id)
        return level >= AccessLevel.PGS

    @staticmethod
    async def grant_sled_ca_from_chat(
        vk_id: int,
        server_id: int,
        peer_id: int,
    ) -> tuple[bool, str]:
        """Вход в беседу след. ЦА: ур. 1 + доступ ЦА."""
        user = await User.get(vk_id=vk_id)
        server = await Server.get(id=server_id)
        access, _ = await UserServerAccess.get_or_create(
            user=user,
            server=server,
            defaults={"access_level": AccessLevel.PGS},
        )
        changed: list[str] = []
        if access.access_level < AccessLevel.PGS:
            access.access_level = AccessLevel.PGS
            access.ca_auto_peer_id = peer_id
            changed.append("ур. 1 (ПГС)")
        if not access.has_ca_access:
            access.has_ca_access = True
            changed.append("доступ ЦА")
        elif access.ca_auto_peer_id is None and access.access_level <= AccessLevel.PGS:
            access.ca_auto_peer_id = peer_id
        await access.save()
        if not changed and access.ca_auto_peer_id == peer_id:
            return False, ""
        if not changed:
            return False, ""
        return True, ", ".join(changed)

    @staticmethod
    async def revoke_sled_ca_from_chat(
        vk_id: int,
        server_id: int,
        peer_id: int,
    ) -> tuple[bool, str]:
        """Выход/кик из беседы след. ЦА: снять только авто-выдачу этой беседы."""
        access = await UserServerAccess.get_or_none(user_id=vk_id, server_id=server_id)
        if not access:
            return False, ""

        if access.access_level >= AccessLevel.ZGS_GOS:
            return False, ""

        spheres = await read_staff_spheres(vk_id, server_id)
        preserve = await UserRepository._sled_ca_leave_preserves_access(access, spheres)

        if preserve:
            if access.ca_auto_peer_id == peer_id:
                access.ca_auto_peer_id = None
                await access.save()
                return True, "привязка к беседе след. ЦА"
            return False, ""

        if access.ca_auto_peer_id != peer_id:
            return False, ""

        access.access_level = 0
        access.has_ca_access = False
        access.ca_auto_peer_id = None
        access.granted_by = None
        await access.save()
        return True, "ур. 1 и доступ ЦА"

    @staticmethod
    async def grant_leader_from_chat(vk_id: int, server_id: int) -> tuple[bool, str]:
        """Вход в беседу руководства ЦА: флаг is_leader."""
        user = await UserRepository.ensure_user(vk_id)
        server = await Server.get(id=server_id)
        access, _ = await UserServerAccess.get_or_create(
            user=user,
            server=server,
            defaults={"access_level": 0},
        )
        if access.is_leader:
            return False, ""
        access.is_leader = True
        await access.save()
        return True, "лидер"

    @staticmethod
    async def revoke_self_ca_access(vk_id: int, server_id: int) -> str | None:
        """Снять с себя доступ ЦА / след. ЦА (авто-уровень из беседы)."""
        access = await UserServerAccess.get_or_none(user_id=vk_id, server_id=server_id)
        if not access:
            return None
        if not access.has_ca_access and not access.ca_auto_peer_id:
            return None

        spheres = await read_staff_spheres(vk_id, server_id)
        preserve = await UserRepository._sled_ca_leave_preserves_access(access, spheres)
        from_sled = bool(access.ca_auto_peer_id)

        if preserve:
            if access.ca_auto_peer_id:
                access.ca_auto_peer_id = None
                await access.save()
                return "привязка к беседе след. ЦА"
            if access.has_ca_access and CENTRAL_APPARATUS not in spheres:
                access.has_ca_access = False
                await access.save()
                return "доступ ЦА"
            return None

        access.has_ca_access = False
        if access.ca_auto_peer_id:
            access.access_level = 0
            access.ca_auto_peer_id = None
            access.granted_by = None
        await access.save()
        return "доступ след. ЦА" if from_sled else "доступ ЦА"

    @staticmethod
    async def get_nickname(vk_id: int, server_id: int) -> str | None:
        access = await UserServerAccess.get_or_none(
            user_id=vk_id,
            server_id=server_id,
        )
        if access and access.nickname and access.nickname.strip():
            return access.nickname.strip()
        return None

    @staticmethod
    async def is_nickname_taken(
        server_id: int,
        nickname: str,
        *,
        exclude_vk_id: int | None = None,
    ) -> bool:
        qs = UserServerAccess.filter(
            server_id=server_id,
            nickname__iexact=nickname,
        )
        if exclude_vk_id:
            qs = qs.exclude(user_id=exclude_vk_id)
        return await qs.exists()

    @staticmethod
    async def set_nickname(vk_id: int, server_id: int, nickname: str) -> User:
        user = await User.get(vk_id=vk_id)
        server = await Server.get(id=server_id)
        access, _ = await UserServerAccess.get_or_create(
            user=user,
            server=server,
            defaults={"access_level": 0},
        )
        access.nickname = nickname
        await access.save()
        user.last_used = datetime.now(timezone.utc)
        await user.save()
        return user

    @staticmethod
    async def clear_nickname(vk_id: int, server_id: int) -> bool:
        access = await UserServerAccess.get_or_none(
            user_id=vk_id,
            server_id=server_id,
        )
        if not access or not (access.nickname and access.nickname.strip()):
            return False
        access.nickname = None
        await access.save()
        return True

    @staticmethod
    async def has_nickname(vk_id: int, server_id: int) -> bool:
        return bool(await UserRepository.get_nickname(vk_id, server_id))

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
