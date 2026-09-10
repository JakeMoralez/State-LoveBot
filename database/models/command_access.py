"""Per-server overrides for bot command min access levels."""

from __future__ import annotations

from tortoise import fields
from tortoise.models import Model


class CommandAccessOverride(Model):
    id = fields.IntField(pk=True)
    server_id = fields.IntField(index=True)
    command_key = fields.CharField(max_length=64)
    min_level = fields.IntField()

    class Meta:
        table = "command_access_overrides"
        unique_together = (("server_id", "command_key"),)
