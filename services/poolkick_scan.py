"""Скан бесед: где пользователь состоит (group API getConversationMembers)."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from vkbottle import API

from database.models.chat import Chat
from database.models.user import AccessLevel
from database.repository.chat_repo import ChatRepository
from database.repository.user_repo import UserRepository
from database.spheres import GOV_STRUCTURES
from services.messaging import MessagingService
from services.staff_spheres import pool_alias_to_sphere

logger = logging.getLogger(__name__)

_SCAN_CONCURRENCY = 5


@dataclass(frozen=True)
class FoundChat:
    peer_id: int
    title: str
    alias: str | None
    sphere: str | None
    pool_id: int | None


@dataclass
class PoolkickScanResult:
    found: list[FoundChat]
    scanned: int
    source_peer_id: int
    source_sphere: str | None


def chat_display_name(chat: Chat | FoundChat) -> str:
    alias = getattr(chat, "alias", None)
    title = (getattr(chat, "title", None) or "").strip()
    if alias and title:
        return f"{alias} — {title}"
    if alias:
        return str(alias)
    if title:
        return title
    peer_id = getattr(chat, "peer_id", 0)
    return f"Беседа {peer_id}"


def sphere_of_chat(chat: Chat) -> str | None:
    pool = getattr(chat, "pool", None)
    pool_name = getattr(pool, "name", None) if pool else None
    return pool_alias_to_sphere(getattr(chat, "alias", None), pool_name)


async def _candidate_chats(
    server_id: int,
    *,
    actor_vk_id: int,
    access_level: int,
    source_peer_id: int,
) -> list[Chat]:
    chats = await ChatRepository.list_all_registered(server_id)
    for chat in chats:
        await chat.fetch_related("pool")

    if access_level >= AccessLevel.ZGS:
        return chats

    is_senior, senior_spheres = await UserRepository.get_senior_status(
        actor_vk_id, server_id
    )
    if not is_senior or not senior_spheres:
        return [c for c in chats if c.peer_id == source_peer_id]

    allowed = set(senior_spheres)
    result: list[Chat] = []
    seen: set[int] = set()
    for chat in chats:
        if chat.peer_id == source_peer_id:
            if chat.peer_id not in seen:
                result.append(chat)
                seen.add(chat.peer_id)
            continue
        sphere = sphere_of_chat(chat)
        if sphere and sphere in allowed and chat.peer_id not in seen:
            result.append(chat)
            seen.add(chat.peer_id)
    return result


async def scan_user_in_chats(
    api: API,
    *,
    server_id: int,
    target_vk_id: int,
    actor_vk_id: int,
    access_level: int,
    source_peer_id: int,
) -> PoolkickScanResult:
    messaging = MessagingService(api)
    candidates = await _candidate_chats(
        server_id,
        actor_vk_id=actor_vk_id,
        access_level=access_level,
        source_peer_id=source_peer_id,
    )
    source_chat = next((c for c in candidates if c.peer_id == source_peer_id), None)
    if source_chat is None:
        source_chat = await ChatRepository.get_by_peer_id(source_peer_id)
        if source_chat:
            await source_chat.fetch_related("pool")
    source_sphere = sphere_of_chat(source_chat) if source_chat else None

    sem = asyncio.Semaphore(_SCAN_CONCURRENCY)
    found: list[FoundChat] = []

    async def _check(chat: Chat) -> FoundChat | None:
        async with sem:
            try:
                members = await messaging.get_member_ids(chat.peer_id)
            except Exception as exc:
                logger.warning(
                    "poolkick scan peer=%s failed: %s", chat.peer_id, exc
                )
                return None
            if target_vk_id not in members:
                return None
            return FoundChat(
                peer_id=chat.peer_id,
                title=chat_display_name(chat),
                alias=chat.alias,
                sphere=sphere_of_chat(chat),
                pool_id=chat.pool_id,
            )

    results = await asyncio.gather(*[_check(chat) for chat in candidates])
    for item in results:
        if item:
            found.append(item)

    found.sort(key=lambda x: (x.sphere or "zzz", x.title.lower()))
    return PoolkickScanResult(
        found=found,
        scanned=len(candidates),
        source_peer_id=source_peer_id,
        source_sphere=source_sphere,
    )


def main_spheres_from_found(found: list[FoundChat]) -> list[str]:
    """Уникальные сферы кроме gos — для кнопок «{S}+гос» / «Только {S}»."""
    ordered: list[str] = []
    seen: set[str] = set()
    for item in found:
        if not item.sphere or item.sphere == GOV_STRUCTURES:
            continue
        if item.sphere not in seen:
            seen.add(item.sphere)
            ordered.append(item.sphere)
    return ordered


def filter_peers_by_scope(
    found: list[FoundChat],
    *,
    scope: str,
    source_peer_id: int,
    sphere_key: str | None = None,
) -> list[FoundChat]:
    if scope == "all":
        return list(found)
    if scope == "this":
        return [f for f in found if f.peer_id == source_peer_id]
    if scope == "sphere" and sphere_key:
        return [f for f in found if f.sphere == sphere_key]
    if scope == "sphere_gos" and sphere_key:
        allowed = {sphere_key, GOV_STRUCTURES}
        return [f for f in found if f.sphere in allowed]
    if scope == "gos_only":
        return [f for f in found if f.sphere == GOV_STRUCTURES]
    return []
