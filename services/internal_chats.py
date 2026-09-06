"""Список и правка бесед для панели (internal HTTP)."""

from __future__ import annotations

import asyncio
import logging

from vkbottle import API

from database.models.chat import Chat
from database.models.chat_kind import KIND_LABELS, ChatKind
from database.models.chat_settings import ChatPeerSettings
from database.models.role_chat import RoleChat
from database.repository.chat_settings_repo import ChatSettingsRepository
from database.spheres import SPHERE_LABELS
from services.chat_kind import (
    apply_chat_kind,
    coerce_chat_kind,
    kind_label,
    peer_member_ids,
    resolve_kind,
    spheres_for_kind,
)

logger = logging.getLogger(__name__)


def _kind_meta() -> list[dict]:
    return [
        {
            "id": kind,
            "label": KIND_LABELS.get(kind, kind),
            "needs_sphere": bool(spheres_for_kind(kind)),
            "spheres": [
                {"id": key, "label": SPHERE_LABELS.get(key, key)}
                for key in spheres_for_kind(kind)
            ],
        }
        for kind in ChatKind.ALL
    ]


def _serialize_settings(settings: ChatPeerSettings) -> dict:
    kind = (settings.chat_kind or "").strip() or ChatKind.GENERAL
    sphere = (settings.sphere or "").strip() or None
    kind, sphere = coerce_chat_kind(kind, sphere)
    return {
        "chat_kind": kind,
        "kind_label": kind_label(kind, sphere),
        "sphere": sphere,
        "kick_on_leave": ChatSettingsRepository.effective_kick_on_leave(settings),
        "kick_on_rejoin": ChatSettingsRepository.effective_kick_on_rejoin(settings),
        "auto_mute_on_join": (settings.auto_mute_on_join or "off").strip() or "off",
        "updated_at": settings.updated_at.isoformat() if settings.updated_at else None,
    }


async def _collect_peer_ids(server_id: int) -> dict[int, dict]:
    peers: dict[int, dict] = {}

    for chat in await Chat.filter(server_id=server_id):
        peer = int(chat.peer_id)
        peers[peer] = {
            "title": (chat.title or "").strip() or None,
            "alias": (chat.alias or "").strip() or None,
        }

    for row in await RoleChat.filter(server_id=server_id):
        peer = int(row.peer_id)
        peers.setdefault(peer, {"title": None, "alias": None})

    for settings in await ChatPeerSettings.filter(server_id=server_id):
        peer = int(settings.peer_id)
        peers.setdefault(peer, {"title": None, "alias": None})

    extra = [p for p in peers if p]
    if extra:
        for settings in await ChatPeerSettings.filter(peer_id__in=extra):
            peers.setdefault(int(settings.peer_id), {"title": None, "alias": None})

    return peers


async def list_chats_payload(api: API, server_id: int) -> dict:
    peers = await _collect_peer_ids(server_id)
    for peer_id in list(peers):
        await resolve_kind(peer_id)
    settings_by_peer = {
        int(row.peer_id): row
        for row in await ChatPeerSettings.filter(peer_id__in=list(peers) or [-1])
    }

    async def _count(peer_id: int) -> int | None:
        try:
            return len(await peer_member_ids(api, peer_id))
        except Exception:
            logger.warning("chat member count failed peer=%s", peer_id)
            return None

    counts = await asyncio.gather(*(_count(peer) for peer in peers), return_exceptions=True)
    count_by_peer: dict[int, int | None] = {}
    for peer, count in zip(peers, counts):
        count_by_peer[peer] = None if isinstance(count, Exception) else count

    chats: list[dict] = []
    for peer_id, meta in peers.items():
        settings = settings_by_peer.get(peer_id)
        if settings is None:
            settings = await ChatSettingsRepository.get(peer_id)
            kind, sphere, sid = await resolve_kind(peer_id)
            if sid is None:
                settings.server_id = server_id
                await settings.save()
        serialized = _serialize_settings(settings)
        title = meta.get("title") or f"Беседа {peer_id - 2_000_000_000}"
        chats.append(
            {
                "peer_id": peer_id,
                "title": title,
                "alias": meta.get("alias"),
                "member_count": count_by_peer.get(peer_id),
                **serialized,
            }
        )

    chats.sort(key=lambda row: ((row.get("kind_label") or ""), row["peer_id"]))
    return {
        "server_id": server_id,
        "kinds": _kind_meta(),
        "chats": chats,
    }


async def patch_chat(
    api: API,
    peer_id: int,
    *,
    server_id: int,
    updated_by: int,
    body: dict,
) -> dict:
    if peer_id < 2_000_000_000:
        raise ValueError("Некорректный peer_id")

    current_kind, current_sphere, _ = await resolve_kind(peer_id)
    kind = str(body["chat_kind"]).strip() if "chat_kind" in body else current_kind
    sphere = body.get("sphere") if "sphere" in body else current_sphere
    if isinstance(sphere, str):
        sphere = sphere.strip() or None

    if "chat_kind" in body or "sphere" in body:
        chat = await Chat.filter(peer_id=peer_id).first()
        await apply_chat_kind(
            peer_id,
            kind,
            server_id=server_id,
            updated_by=updated_by,
            sphere=sphere,
            api=api,
            title=(chat.title if chat else None),
        )

    mode_fields = (
        ("kick_on_leave", True),
        ("kick_on_rejoin", False),
        ("auto_mute_on_join", False),
    )
    for field, allow_ask in mode_fields:
        if field not in body:
            continue
        mode = ChatSettingsRepository.normalize_mode(str(body[field]), allow_ask=allow_ask)
        if not mode:
            raise ValueError(f"Недопустимый режим для {field}")
        await ChatSettingsRepository.set_mode(
            peer_id,
            field,
            mode,
            updated_by=updated_by,
            allow_ask=allow_ask,
        )

    settings = await ChatSettingsRepository.get(peer_id)
    chat = await Chat.filter(peer_id=peer_id).first()
    title = (chat.title if chat and chat.title else None) or f"Беседа {peer_id - 2_000_000_000}"
    try:
        member_count = len(await peer_member_ids(api, peer_id))
    except Exception:
        member_count = None
    return {
        "peer_id": peer_id,
        "title": title,
        "alias": (chat.alias if chat else None),
        "member_count": member_count,
        **_serialize_settings(settings),
    }
