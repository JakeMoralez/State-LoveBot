"""Логи модерации (kick / pullkick)."""

from __future__ import annotations

from tortoise import fields
from tortoise.models import Model


class ModerationLog(Model):
    id = fields.IntField(pk=True)
    server = fields.ForeignKeyField(
        "models.Server",
        related_name="moderation_logs",
        on_delete=fields.CASCADE,
    )
    pool = fields.ForeignKeyField(
        "models.Pool",
        related_name="moderation_logs",
        null=True,
        on_delete=fields.SET_NULL,
    )
    actor_vk_id = fields.BigIntField()
    target_vk_id = fields.BigIntField()
    action = fields.CharField(max_length=32)  # kick, pullkick
    reason = fields.TextField(null=True)
    peer_id = fields.BigIntField(null=True)
    success = fields.BooleanField(default=True)
    details = fields.TextField(null=True)
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "moderation_logs"
