"""Повестки / уведомления (legacy-функционал)."""

from __future__ import annotations

from tortoise import fields
from tortoise.models import Model


class Notification(Model):
    id = fields.IntField(pk=True)
    server = fields.ForeignKeyField(
        "models.Server",
        related_name="notifications",
        null=True,
        on_delete=fields.SET_NULL,
    )
    judge_id = fields.BigIntField()
    judge_peer_id = fields.BigIntField(null=True)
    judge_name = fields.CharField(max_length=128)
    target_nickname = fields.CharField(max_length=128)
    message = fields.TextField()
    status = fields.CharField(max_length=32, default="pending")
    created_at = fields.DatetimeField(auto_now_add=True)
    processed_by = fields.BigIntField(null=True)
    processed_by_name = fields.CharField(max_length=128, null=True)
    processed_at = fields.DatetimeField(null=True)
    reject_reason = fields.TextField(null=True)
    processed_by_peer_id = fields.BigIntField(null=True)

    class Meta:
        table = "notifications"
