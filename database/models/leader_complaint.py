"""Увиденные жалобы на лидеров (уведомления в ruk_gos)."""

from __future__ import annotations

from tortoise import fields
from tortoise.models import Model


class LeaderComplaintSeen(Model):
    """Темы раздела жалоб на лидеров, которые бот уже видел."""

    id = fields.IntField(pk=True)
    thread_id = fields.BigIntField(unique=True)
    server_id = fields.IntField(index=True)
    notified = fields.BooleanField(default=False)
    first_seen_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "leader_complaint_seen"
