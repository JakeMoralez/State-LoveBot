"""Учёт закрытых судебных исков (по thread_id)."""

from __future__ import annotations

from tortoise import fields
from tortoise.models import Model


class CourtClaimClose(Model):
    """Один thread_id — одна запись (кому засчитано закрытие)."""

    id = fields.IntField(pk=True)
    thread_id = fields.BigIntField(unique=True)
    server_id = fields.IntField()
    closed_by_vk_id = fields.BigIntField()
    forum_member_id = fields.CharField(max_length=32, null=True)
    closed_at = fields.DatetimeField()

    class Meta:
        table = "court_claim_closes"
