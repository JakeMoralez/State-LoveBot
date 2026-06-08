"""Модель VK-беседы, привязанной к серверу и пулу."""

from __future__ import annotations

from tortoise import fields
from tortoise.models import Model


class Chat(Model):
    id = fields.IntField(pk=True)
    peer_id = fields.BigIntField(unique=True)
    server = fields.ForeignKeyField(
        "models.Server",
        related_name="chats",
        on_delete=fields.CASCADE,
    )
    pool = fields.ForeignKeyField(
        "models.Pool",
        related_name="chats",
        null=True,
        on_delete=fields.SET_NULL,
    )
    title = fields.CharField(max_length=256, null=True)
    alias = fields.CharField(max_length=64, null=True)
    registered_by = fields.BigIntField(null=True)
    registered_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "chats"
        unique_together = (("server_id", "alias"),)

    @property
    def chat_id(self) -> int:
        """VK chat_id из peer_id."""
        return int(self.peer_id - 2_000_000_000)
