"""Привязка VK-бесед к форумным ролям (судьи, адвокаты и т.д.)."""

from __future__ import annotations

from tortoise import fields
from tortoise.models import Model


class ForumRoleKey:
    JUDGE = "judge"
    ATTORNEY = "attorney"
    LEADER = "leader"
    ADMIN = "admin"
    MINISTRY = "ministry_of_justice"
    CONGRESS = "congress"


class RoleChat(Model):
    role = fields.CharField(max_length=32, pk=True)
    peer_id = fields.BigIntField()
    server = fields.ForeignKeyField(
        "models.Server",
        related_name="role_chats",
        null=True,
        on_delete=fields.SET_NULL,
    )
    registered_by = fields.BigIntField(null=True)
    registered_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "role_chats"
