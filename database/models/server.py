"""Модель игрового сервера / дистрикта."""

from __future__ import annotations

from tortoise import fields
from tortoise.models import Model


class Server(Model):
    id = fields.IntField(pk=True)
    slug = fields.CharField(max_length=64, unique=True)
    name = fields.CharField(max_length=128)
    is_active = fields.BooleanField(default=True)
    log_peer_id = fields.BigIntField(null=True)
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "servers"

    def __str__(self) -> str:
        return f"{self.name} ({self.slug})"
