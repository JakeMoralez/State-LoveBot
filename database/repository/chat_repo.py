"""Репозиторий VK-бесед."""

from __future__ import annotations

import re

from database.models.chat import Chat

ALIAS_RE = re.compile(r"^[a-z][a-z0-9_]{1,63}$")


class ChatRepository:
    @staticmethod
    def validate_alias(alias: str) -> tuple[bool, str]:
        alias = alias.strip().lower()
        if not ALIAS_RE.match(alias):
            return (
                False,
                "Алиас: латиница, цифры, _, от 2 символов (напр. court, lead_gos).",
            )
        return True, alias

    @staticmethod
    async def get_by_peer_id(peer_id: int) -> Chat | None:
        return await Chat.filter(peer_id=peer_id).prefetch_related(
            "server", "pool"
        ).first()

    @staticmethod
    async def get_by_alias(server_id: int, alias: str) -> Chat | None:
        ok, normalized = ChatRepository.validate_alias(alias)
        if not ok:
            return None
        return await Chat.filter(
            server_id=server_id,
            alias=normalized,
        ).prefetch_related("server", "pool").first()

    @staticmethod
    async def register_chat(
        peer_id: int,
        server_id: int,
        pool_id: int | None,
        alias: str | None,
        title: str | None,
        registered_by: int,
    ) -> Chat:
        normalized_alias = None
        if alias:
            ok, normalized_alias = ChatRepository.validate_alias(alias)
            if not ok:
                raise ValueError(normalized_alias)

        await Chat.update_or_create(
            peer_id=peer_id,
            defaults={
                "server_id": server_id,
                "pool_id": pool_id,
                "alias": normalized_alias,
                "title": title,
                "registered_by": registered_by,
            },
        )
        chat = await ChatRepository.get_by_peer_id(peer_id)
        if chat is None:
            raise RuntimeError(f"Не удалось зарегистрировать беседу peer_id={peer_id}")
        return chat

    @staticmethod
    async def list_by_pool(pool_id: int) -> list[Chat]:
        return await Chat.filter(pool_id=pool_id).order_by("alias", "peer_id")

    @staticmethod
    async def list_gos_shared(server_id: int) -> list[Chat]:
        """Общие gos-беседы сервера (lead_gos, sled_gos, offtop_gos и т.д.)."""
        return await Chat.filter(
            server_id=server_id,
            alias__endswith="_gos",
        ).order_by("alias", "peer_id")

    @staticmethod
    async def list_for_pullkick(server_id: int, pool_id: int) -> tuple[list[Chat], int]:
        """Беседы пула + общие *_gos (без дублей). Возвращает (список, число gos)."""
        pool_chats = await ChatRepository.list_by_pool(pool_id)
        gos_chats = await ChatRepository.list_gos_shared(server_id)
        seen = {chat.peer_id for chat in pool_chats}
        merged = list(pool_chats)
        gos_added = 0
        for chat in gos_chats:
            if chat.peer_id not in seen:
                seen.add(chat.peer_id)
                merged.append(chat)
                gos_added += 1
        return merged, gos_added

    @staticmethod
    async def list_all_registered(server_id: int) -> list[Chat]:
        """Все зарегистрированные беседы сервера (где бот привязан через /regchat)."""
        return await Chat.filter(server_id=server_id).order_by("alias", "peer_id")

    @staticmethod
    async def list_aliases(server_id: int, pool_id: int | None = None) -> list[Chat]:
        qs = Chat.filter(server_id=server_id).exclude(alias=None)
        if pool_id is not None:
            qs = qs.filter(pool_id=pool_id)
        return await qs.order_by("alias")

    @staticmethod
    async def unlink_from_pool(peer_id: int) -> Chat | None:
        chat = await ChatRepository.get_by_peer_id(peer_id)
        if not chat or chat.pool_id is None:
            return None
        chat.pool_id = None
        chat.alias = None
        await chat.save()
        return chat
