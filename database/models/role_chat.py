"""Привязка VK-бесед к форумным ролям (судьи, адвокаты и т.д.) — на каждый сервер."""

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
    SLED_CA = "sled_ca"


class RoleChat(Model):
    id = fields.IntField(pk=True)
    role = fields.CharField(max_length=32)
    server = fields.ForeignKeyField(
        "models.Server",
        related_name="role_chats",
        on_delete=fields.CASCADE,
    )
    peer_id = fields.BigIntField()
    registered_by = fields.BigIntField(null=True)
    registered_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "role_chats"
        unique_together = (("server_id", "role"),)

    def __str__(self) -> str:
        return f"{self.role}@{self.server_id}"
