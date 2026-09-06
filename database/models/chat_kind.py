"""Типы бесед (/chatsettings пункт 4)."""

from __future__ import annotations


class ChatKind:
    GENERAL = "general"
    LEADER = "leader"
    JUDGE = "judge"
    STAFF = "staff"
    SLED_CA = "sled_ca"
    STRUCTURE_LEAD = "structure_lead"
    CONGRESS = "congress"

    ALL = (
        GENERAL,
        LEADER,
        JUDGE,
        STAFF,
        SLED_CA,
        STRUCTURE_LEAD,
        CONGRESS,
    )


KIND_LABELS: dict[str, str] = {
    ChatKind.GENERAL: "Общая",
    ChatKind.LEADER: "Лидерская",
    ChatKind.JUDGE: "Судейская",
    ChatKind.STAFF: "Следящие",
    ChatKind.SLED_CA: "След. ЦА",
    ChatKind.STRUCTURE_LEAD: "Главная следящая администрация",
    ChatKind.CONGRESS: "Конгресс",
}

STRUCTURE_SPHERE_KEYS: tuple[str, ...] = (
    "gov_structures",
    "illegal_structures",
    "server",
)
