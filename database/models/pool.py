"""Модель пула бесед."""

from __future__ import annotations

from tortoise import fields
from tortoise.models import Model


class Pool(Model):
    id = fields.IntField(pk=True)
    server = fields.ForeignKeyField(
        "models.Server",
        related_name="pools",
        on_delete=fields.CASCADE,
    )
    name = fields.CharField(max_length=128)
    description = fields.TextField(null=True)
    created_at = fields.DatetimeField(auto_now_add=True)
    created_by = fields.BigIntField(null=True)

    chats: fields.ReverseRelation["Chat"]

    class Meta:
        table = "pools"
        unique_together = (("server_id", "name"),)

    def __str__(self) -> str:
        return self.name
