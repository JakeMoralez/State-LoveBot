"""Настройки беседы: rejoinkick при выходе."""

from __future__ import annotations

from tortoise import fields
from tortoise.models import Model


class GuardMode:
    OFF = "off"
    ON = "on"
    ASK = "ask"

    ALL = (OFF, ON, ASK)


class ChatPeerSettings(Model):
    peer_id = fields.BigIntField(pk=True)
    restrict_invites = fields.CharField(max_length=8, default=GuardMode.OFF)
    rejoin_kick = fields.CharField(max_length=8, default=GuardMode.OFF)
    kick_on_leave = fields.CharField(max_length=8, default=GuardMode.OFF)
    kick_on_rejoin = fields.CharField(max_length=8, default=GuardMode.OFF)
    auto_mute_on_join = fields.CharField(max_length=8, default=GuardMode.OFF)
    updated_by = fields.BigIntField(null=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "chat_peer_settings"


class ChatLeftMember(Model):
    """Участник сам вышел — для опции rejoin_kick."""

    id = fields.IntField(pk=True)
    peer_id = fields.BigIntField()
    user_id = fields.BigIntField()
    left_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "chat_left_members"
        unique_together = (("peer_id", "user_id"),)
