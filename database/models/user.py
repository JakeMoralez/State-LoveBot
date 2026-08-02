"""Модели пользователей и уровней доступа."""

from __future__ import annotations

from tortoise import fields
from tortoise.models import Model


class AccessLevel:
    """Числовые уровни доступа (1–11)."""

    PGS = 1
    SUPERVISOR = 2
    ZGS = 3
    GS = 4
    STRUCTURE_SUPERVISOR = 5  # Следящий структуры (между ГС сферы и ЗГС структуры)
    ZGS_GOS = 6
    GS_GOS = 7
    CURATOR = 8
    ZGA = 9
    GA = 10
    DEVELOPER = 11

    NAMES: dict[int, str] = {
        1: "ПГС",
        2: "Следящий",
        3: "ЗГС",
        4: "ГС",
        5: "Следящий структуры",
        6: "ЗГС ГОС",
        7: "ГС ГОС",
        8: "Куратор",
        9: "ЗГА",
        10: "ГА",
        11: "Разработчик",
    }

    @classmethod
    def title(cls, level: int) -> str:
        return cls.NAMES.get(level, f"Уровень {level}")


class User(Model):
    vk_id = fields.BigIntField(pk=True)
    username = fields.CharField(max_length=128, null=True)
    nickname = fields.CharField(max_length=64, null=True)
    added_by = fields.BigIntField(null=True)
    added_at = fields.DatetimeField(auto_now_add=True)
    last_used = fields.DatetimeField(null=True)
    note = fields.TextField(null=True)

    # Legacy-флаги (для совместимости при миграции с users.db)
    is_admin = fields.BooleanField(default=False)
    is_judge = fields.BooleanField(default=False)
    is_attorney = fields.BooleanField(default=False)
    is_leader = fields.BooleanField(default=False)
    is_congress_speaker = fields.BooleanField(default=False)
    is_congress_vice = fields.BooleanField(default=False)

    server_accesses: fields.ReverseRelation["UserServerAccess"]

    class Meta:
        table = "users"

    def __str__(self) -> str:
        return self.nickname or self.username or str(self.vk_id)


class UserServerAccess(Model):
    """Уровень доступа пользователя на конкретном сервере."""

    id = fields.IntField(pk=True)
    user = fields.ForeignKeyField(
        "models.User",
        related_name="server_accesses",
        on_delete=fields.CASCADE,
    )
    server = fields.ForeignKeyField(
        "models.Server",
        related_name="user_accesses",
        on_delete=fields.CASCADE,
    )
    access_level = fields.IntField(default=AccessLevel.PGS)
    nickname = fields.CharField(max_length=64, null=True)
    is_judge = fields.BooleanField(default=False)
    is_attorney = fields.BooleanField(default=False)
    is_leader = fields.BooleanField(default=False)
    is_congress_speaker = fields.BooleanField(default=False)
    is_congress_vice = fields.BooleanField(default=False)
    granted_by = fields.BigIntField(null=True)
    granted_at = fields.DatetimeField(auto_now_add=True)
    has_ca_access = fields.BooleanField(default=False)
    ca_auto_peer_id = fields.BigIntField(null=True)

    class Meta:
        table = "user_server_access"
        unique_together = (("user_id", "server_id"),)
