"""Тип беседы: хранение, синхронизация role_chats и доступ по членству."""

from __future__ import annotations

import logging

from vkbottle import API

from database.models.chat_kind import (
    KIND_LABELS,
    STRUCTURE_SPHERE_KEYS,
    ChatKind,
)
from database.models.chat_settings import ChatPeerSettings
from database.models.role_chat import ForumRoleKey
from database.repository.chat_repo import ChatRepository
from database.repository.chat_settings_repo import ChatSettingsRepository
from database.repository.forum_role_repo import ForumRoleRepository
from database.repository.user_repo import UserRepository
from database.spheres import ALL_SPHERE_KEYS, SPHERE_LABELS, format_spheres_display
from middlewares.access import AccessChecker
from services.panel_client import sync_staff_sphere

logger = logging.getLogger(__name__)

KIND_TO_ROLE: dict[str, str] = {
    ChatKind.LEADER: ForumRoleKey.LEADER,
    ChatKind.JUDGE: ForumRoleKey.JUDGE,
    ChatKind.SLED_CA: ForumRoleKey.SLED_CA,
    ChatKind.CONGRESS: ForumRoleKey.CONGRESS,
}

ROLE_TO_KIND: dict[str, str] = {role: kind for kind, role in KIND_TO_ROLE.items()}


def kind_label(kind: str, sphere: str | None = None) -> str:
    base = KIND_LABELS.get(kind, kind)
    if kind in (ChatKind.STAFF, ChatKind.STRUCTURE_LEAD) and sphere:
        return f"{base} · {SPHERE_LABELS.get(sphere, sphere)}"
    return base


def spheres_for_kind(kind: str) -> tuple[str, ...]:
    if kind == ChatKind.STAFF:
        return ALL_SPHERE_KEYS
    if kind == ChatKind.STRUCTURE_LEAD:
        return STRUCTURE_SPHERE_KEYS
    return ()


async def resolve_kind(
    peer_id: int,
) -> tuple[str, str | None, int | None]:
    """Вернуть (kind, sphere, server_id) с ленивым бэкофиллом из role_chats."""
    settings = await ChatSettingsRepository.get(peer_id)
    kind = (settings.chat_kind or "").strip() or ChatKind.GENERAL
    sphere = (settings.sphere or "").strip() or None
    server_id = settings.server_id

    if kind == ChatKind.GENERAL:
        role_chat = await ForumRoleRepository.get_role_chat_by_peer(peer_id)
        if role_chat and role_chat.role in ROLE_TO_KIND:
            kind = ROLE_TO_KIND[role_chat.role]
            server_id = server_id or role_chat.server_id
            settings.chat_kind = kind
            settings.server_id = server_id
            await settings.save()
    return kind, sphere, server_id


async def list_kind_peers(
    server_id: int,
    kind: str,
    sphere: str | None = None,
) -> list[int]:
    peers: set[int] = set()
    qs = ChatPeerSettings.filter(chat_kind=kind)
    if sphere:
        qs = qs.filter(sphere=sphere)
    for row in await qs:
        if row.server_id is None or int(row.server_id) == int(server_id):
            peers.add(int(row.peer_id))

    role = KIND_TO_ROLE.get(kind)
    if role:
        for peer in await ForumRoleRepository.list_role_chat_peers(role, server_id):
            if sphere:
                settings = await ChatPeerSettings.get_or_none(peer_id=peer)
                if settings and (settings.sphere or "") != sphere:
                    continue
            peers.add(int(peer))
    return sorted(peers)


async def peer_member_ids(api: API, peer_id: int) -> list[int]:
    from config.settings import VK_USER_TOKEN
    from services.messaging import MessagingService

    user_api = API(token=VK_USER_TOKEN) if VK_USER_TOKEN else None
    return await MessagingService(api, user_api=user_api).get_member_ids(peer_id)


async def user_in_other_kind_chat(
    api: API,
    user_id: int,
    server_id: int,
    kind: str,
    exclude_peer: int,
    sphere: str | None = None,
) -> bool:
    for peer in await list_kind_peers(server_id, kind, sphere=sphere):
        if peer == exclude_peer:
            continue
        members = await peer_member_ids(api, peer)
        if user_id in members:
            return True
    return False


async def apply_chat_kind(
    peer_id: int,
    kind: str,
    *,
    server_id: int,
    updated_by: int,
    sphere: str | None = None,
    api: API | None = None,
    title: str | None = None,
) -> tuple[str, str | None]:
    if kind not in ChatKind.ALL:
        raise ValueError("Неизвестный тип беседы")

    needed = spheres_for_kind(kind)
    if needed:
        if not sphere or sphere not in needed:
            raise ValueError("Укажите сферу для этого типа беседы")
    else:
        sphere = None

    old_kind, old_sphere, _old_server = await resolve_kind(peer_id)
    settings = await ChatSettingsRepository.get(peer_id)
    settings.chat_kind = kind
    settings.sphere = sphere
    settings.server_id = server_id
    settings.updated_by = updated_by
    await settings.save()

    await _sync_role_binding(
        peer_id,
        kind,
        server_id=server_id,
        registered_by=updated_by,
        title=title,
    )

    if api is not None and (old_kind, old_sphere) != (kind, sphere):
        await recalc_peer_members(
            api,
            peer_id,
            server_id,
            old_kind=old_kind,
            old_sphere=old_sphere,
            new_kind=kind,
            new_sphere=sphere,
        )
    return old_kind, old_sphere


async def _sync_role_binding(
    peer_id: int,
    kind: str,
    *,
    server_id: int,
    registered_by: int,
    title: str | None,
) -> None:
    role = KIND_TO_ROLE.get(kind)
    if role:
        await ForumRoleRepository.save_role_chat(
            role, peer_id, registered_by, server_id
        )
    else:
        await ForumRoleRepository.delete_role_chat_by_peer(peer_id)

    if kind == ChatKind.CONGRESS:
        from database.repository.congress_repo import CongressRepository

        try:
            await CongressRepository.register_chat(
                peer_id,
                registered_by,
                server_id,
                title=title,
            )
        except ValueError as exc:
            logger.info("congress register peer=%s: %s", peer_id, exc)


async def recalc_peer_members(
    api: API,
    peer_id: int,
    server_id: int,
    *,
    old_kind: str,
    old_sphere: str | None,
    new_kind: str,
    new_sphere: str | None,
) -> None:
    try:
        members = await peer_member_ids(api, peer_id)
    except Exception:
        logger.exception("recalc members failed peer=%s", peer_id)
        return
    for user_id in members:
        if user_id <= 0:
            continue
        await apply_leave_effects(
            api, peer_id, user_id, server_id, old_kind, old_sphere
        )
        await apply_join_effects(
            api, peer_id, user_id, server_id, new_kind, new_sphere
        )


async def apply_join_effects(
    api: API,
    peer_id: int,
    user_id: int,
    server_id: int,
    kind: str,
    sphere: str | None,
) -> str | None:
    if user_id <= 0:
        return None
    if kind == ChatKind.LEADER:
        await UserRepository.ensure_user(vk_id=user_id)
        changed, _ = await UserRepository.grant_leader_from_chat(user_id, server_id)
        return None if not changed else None
    if kind == ChatKind.JUDGE:
        await UserRepository.ensure_user(vk_id=user_id)
        access = await ForumRoleRepository._ensure_access(user_id, server_id)
        if not access.is_judge:
            access.is_judge = True
            await access.save()
        return None
    if kind == ChatKind.SLED_CA:
        await UserRepository.ensure_user(vk_id=user_id)
        changed, _detail = await UserRepository.grant_sled_ca_from_chat(
            user_id, server_id, peer_id
        )
        if changed:
            from services.panel_client import sync_staff_spheres

            await sync_staff_spheres(
                user_id, grant_central_apparatus=True, server_id=server_id
            )
        return None
    if kind == ChatKind.STAFF and sphere:
        await sync_staff_sphere(user_id, sphere, grant=True, server_id=server_id)
    return None


async def apply_leave_effects(
    api: API,
    peer_id: int,
    user_id: int,
    server_id: int,
    kind: str,
    sphere: str | None,
) -> str | None:
    if user_id <= 0 or kind in (ChatKind.GENERAL, ChatKind.STRUCTURE_LEAD, ChatKind.CONGRESS):
        if kind == ChatKind.CONGRESS:
            from database.repository.congress_repo import CongressRepository

            await CongressRepository.revoke_officer_on_leave(peer_id, user_id, server_id)
        return None

    still = await user_in_other_kind_chat(
        api, user_id, server_id, kind, peer_id, sphere=sphere
    )
    if still:
        return None

    if kind == ChatKind.LEADER:
        await ForumRoleRepository.clear_leader_role(user_id, server_id)
        return None
    if kind == ChatKind.JUDGE:
        await ForumRoleRepository.clear_judge_role(user_id, server_id)
        return None
    if kind == ChatKind.SLED_CA:
        changed, _detail = await UserRepository.revoke_sled_ca_from_chat(
            user_id, server_id, peer_id
        )
        if changed:
            from services.panel_client import sync_staff_spheres

            await sync_staff_spheres(
                user_id, grant_central_apparatus=False, server_id=server_id
            )
        return None
    if kind == ChatKind.STAFF and sphere:
        await sync_staff_sphere(user_id, sphere, grant=False, server_id=server_id)
    return None


async def format_kind_line(peer_id: int) -> str:
    kind, sphere, _ = await resolve_kind(peer_id)
    return f"🏷 Тип беседы — {kind_label(kind, sphere)}"


async def resolve_server_for_peer(peer_id: int, user_id: int = 0) -> int:
    _, _, server_id = await resolve_kind(peer_id)
    if server_id:
        return int(server_id)
    chat = await ChatRepository.get_by_peer_id(peer_id)
    if chat:
        return int(chat.server_id)
    return await AccessChecker.resolve_server_id(peer_id, user_id)


def format_spheres_hint(kind: str) -> str:
    keys = spheres_for_kind(kind)
    return format_spheres_display(list(keys)) if keys else ""


async def handle_peer_join(peer_id: int, user_id: int, api: API) -> str | None:
    kind, sphere, server_id = await resolve_kind(peer_id)
    if not server_id:
        server_id = await resolve_server_for_peer(peer_id, user_id)
    return await apply_join_effects(api, peer_id, user_id, int(server_id), kind, sphere)


async def handle_peer_leave(peer_id: int, user_id: int, api: API) -> str | None:
    kind, sphere, server_id = await resolve_kind(peer_id)
    if not server_id:
        server_id = await resolve_server_for_peer(peer_id, user_id)
    return await apply_leave_effects(api, peer_id, user_id, int(server_id), kind, sphere)
