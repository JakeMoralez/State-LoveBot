"""Учёт закрытых судебных исков и увиденных тем (для уведомлений)."""

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


class CourtClaimSeen(Model):
    """Темы раздела исков, которые бот уже видел (для «новый иск» в беседу судей)."""

    id = fields.IntField(pk=True)
    thread_id = fields.BigIntField(unique=True)
    server_id = fields.IntField(index=True)
    notified = fields.BooleanField(default=False)
    first_seen_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "court_claim_seen"
