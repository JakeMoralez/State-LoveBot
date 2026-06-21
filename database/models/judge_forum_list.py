"""Настройки автообновления темы «Список судей» на форуме."""

from __future__ import annotations

from tortoise import fields
from tortoise.models import Model


class JudgeForumListSettings(Model):
    server_id = fields.IntField(pk=True)
    thread_id = fields.IntField(null=True)
    enabled = fields.BooleanField(default=True)
    body_template = fields.TextField(default="")
    line_template = fields.TextField(default="")
    empty_text = fields.TextField(default="")
    updated_by_vk_id = fields.BigIntField(null=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "judge_forum_list_settings"
