"""Игровые формы судей (uvaloff, apunishoff, notif и т.д.)."""

from __future__ import annotations

from tortoise import fields
from tortoise.models import Model


class CourtFormStatus:
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class CourtFormType:
    UVALOFF = "uvaloff"
    APUNISHOFF = "apunishoff"
    UNAPUNISHOFF = "unapunishoff"
    NOTIF = "notif"


class CourtForm(Model):
    id = fields.IntField(pk=True)
    server = fields.ForeignKeyField(
        "models.Server",
        related_name="court_forms",
        on_delete=fields.CASCADE,
    )
    judge_id = fields.BigIntField()
    judge_peer_id = fields.BigIntField(null=True)
    form_type = fields.CharField(max_length=32)
    target_nickname = fields.CharField(max_length=128)
    lawsuit_id = fields.IntField(null=True)
    stars = fields.IntField(null=True)
    message = fields.TextField(null=True)
    raw_text = fields.TextField()
    batch_id = fields.CharField(max_length=32, null=True)
    status = fields.CharField(max_length=32, default=CourtFormStatus.PENDING)
    created_at = fields.DatetimeField(auto_now_add=True)
    processed_by = fields.BigIntField(null=True)
    processed_at = fields.DatetimeField(null=True)
    reject_reason = fields.TextField(null=True)

    class Meta:
        table = "court_forms"
