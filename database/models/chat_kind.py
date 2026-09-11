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
    MANAGERS = "managers"

    ALL = (
        GENERAL,
        LEADER,
        JUDGE,
        STAFF,
        STRUCTURE_LEAD,
        CONGRESS,
        MANAGERS,
    )


KIND_LABELS: dict[str, str] = {
    ChatKind.GENERAL: "Общая",
    ChatKind.LEADER: "Лидерская",
    ChatKind.JUDGE: "Судейская",
    ChatKind.STAFF: "Следящие",
    ChatKind.SLED_CA: "След. ЦА",
    ChatKind.STRUCTURE_LEAD: "Главная следящая администрация",
    ChatKind.CONGRESS: "Конгресс",
    ChatKind.MANAGERS: "Управляющие",
}

STRUCTURE_SPHERE_KEYS: tuple[str, ...] = (
    "gov_structures",
    "illegal_structures",
    "server",
)

# Следящие: без «сервер». ГОС / нелег только метка, доступ не выдают.
STAFF_SPHERE_KEYS: tuple[str, ...] = (
    "central_apparatus",
    "justice",
    "defense",
    "health",
    "gov_structures",
    "illegal_structures",
)

STAFF_ACCESS_SPHERE_KEYS: tuple[str, ...] = (
    "justice",
    "defense",
    "health",
)
