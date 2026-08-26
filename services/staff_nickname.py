"""Staff nickname tags — parity with State-LoveAdmin staff_nickname.py."""

from __future__ import annotations

import re

from database.models.user import AccessLevel
from database.spheres import (
    CENTRAL_APPARATUS,
    DEFENSE,
    GOV_STRUCTURES,
    HEALTH,
    ILLEGAL_STRUCTURES,
    JUSTICE,
)

_TAG_PREFIX_RE = re.compile(r"^[\[［]([^\］\]]+)[\]］]\s*")

LEVEL_NICK_TAGS: dict[int, str] = {
    AccessLevel.PGS: "ПС",
    AccessLevel.SUPERVISOR: "След.",
    AccessLevel.ZGS: "ЗГС",
    AccessLevel.GS: "ГС",
    AccessLevel.STRUCTURE_SUPERVISOR: "След.",
    AccessLevel.ZGS_GOS: "ЗГС",
    AccessLevel.GS_GOS: "ГС",
    AccessLevel.CURATOR: "Куратор",
    AccessLevel.ZGA: "ЗГА",
    AccessLevel.GA: "ГА",
    AccessLevel.DEVELOPER: "Разработчик",
}

MINISTRY_NICK_TAGS: dict[str, str] = {
    CENTRAL_APPARATUS: "ЦА",
    JUSTICE: "МЮ",
    DEFENSE: "МО",
    HEALTH: "МЗ",
}

MINISTRY_NICK_TAG_ORDER: tuple[str, ...] = (
    CENTRAL_APPARATUS,
    JUSTICE,
    DEFENSE,
    HEALTH,
)

STRUCTURE_NICK_TAGS: dict[str, str] = {
    GOV_STRUCTURES: "ГОС",
    ILLEGAL_STRUCTURES: "Нелег",
}

STRUCTURE_NICK_TAG_ORDER: tuple[str, ...] = (
    GOV_STRUCTURES,
    ILLEGAL_STRUCTURES,
)


def extract_leading_nickname_tag(raw: str | None) -> str | None:
    rest = (raw or "").strip()
    match = _TAG_PREFIX_RE.match(rest)
    if not match:
        return None
    inner = match.group(1).strip()
    return inner or None


def normalize_custom_tag(tag: str | None) -> str | None:
    if tag is None:
        return None
    t = tag.strip().strip("[]［］").strip()
    if not t:
        return None
    if len(t) > 24 or "[" in t or "]" in t or "［" in t or "］" in t:
        raise ValueError("Тег: до 24 символов, без скобок")
    return t


def strip_nickname_tags(raw: str | None) -> str:
    rest = (raw or "").strip()
    if not rest:
        return ""
    while True:
        match = _TAG_PREFIX_RE.match(rest)
        if not match:
            break
        rest = rest[match.end() :].strip()
    return rest


def rewrite_legacy_nickname_tags(nickname: str) -> str:
    text = (nickname or "").strip()
    if not text:
        return text
    replacements = (
        ("След.стр Гос", "След. ГОС"),
        ("След.стр ГОС", "След. ГОС"),
        ("ЗГС Гос", "ЗГС ГОС"),
        ("ГС Гос", "ГС ГОС"),
        ("След.стр", "След."),
        ("ПГС ", "ПС "),
        ("ПГС]", "ПС]"),
    )
    for old, new in replacements:
        text = text.replace(f"[{old}]", f"[{new}]")
        text = text.replace(f"［{old}］", f"[{new}]")
    return text.replace("［", "[").replace("］", "]")


def pick_sphere_nick_tag(spheres: list[str], access_level: int) -> str | None:
    if access_level >= AccessLevel.CURATOR:
        return None

    if access_level >= AccessLevel.STRUCTURE_SUPERVISOR:
        if GOV_STRUCTURES in spheres:
            return STRUCTURE_NICK_TAGS[GOV_STRUCTURES]
        tags = [
            STRUCTURE_NICK_TAGS[key]
            for key in STRUCTURE_NICK_TAG_ORDER
            if key in spheres and key != GOV_STRUCTURES
        ]
        return "&".join(tags) if tags else None

    tags = [MINISTRY_NICK_TAGS[key] for key in MINISTRY_NICK_TAG_ORDER if key in spheres]
    return "&".join(tags) if tags else None


def ministry_sphere_nick_tag(spheres: list[str] | None) -> str | None:
    tags = [MINISTRY_NICK_TAGS[key] for key in MINISTRY_NICK_TAG_ORDER if key in (spheres or [])]
    return "&".join(tags) if tags else None


def _spheres_without(main: list[str], extra: list[str]) -> list[str]:
    skip = set(extra)
    return [key for key in main if key not in skip]


def format_staff_nickname(
    clean_name: str,
    access_level: int,
    spheres: list[str],
    *,
    custom_tag: str | None = None,
    is_senior: bool = False,
    senior_spheres: list[str] | None = None,
) -> str:
    name = strip_nickname_tags(clean_name).strip()
    if not name:
        raise ValueError("Укажите имя для никнейма")

    if access_level >= AccessLevel.DEVELOPER:
        tag = normalize_custom_tag(custom_tag) or LEVEL_NICK_TAGS[AccessLevel.DEVELOPER]
        bracket = f"[{tag}]"
    else:
        level_tag = LEVEL_NICK_TAGS.get(access_level) or AccessLevel.title(access_level)
        extra = list(senior_spheres or []) if is_senior else []
        extra_tag = ministry_sphere_nick_tag(extra) if extra else None
        leftover = _spheres_without(list(spheres or []), extra)

        if access_level >= AccessLevel.CURATOR:
            bracket = f"[{level_tag}]"
        elif extra_tag and AccessLevel.SUPERVISOR <= access_level < AccessLevel.ZGS:
            follow_tag = pick_sphere_nick_tag(leftover, AccessLevel.SUPERVISOR) if leftover else None
            senior_part = f"Ст. След. {extra_tag}"
            if follow_tag:
                bracket = f"[{senior_part} | След. {follow_tag}]"
            else:
                bracket = f"[{senior_part}]"
        else:
            main_keys = leftover if extra_tag and leftover else list(spheres or [])
            main_sphere_tag = pick_sphere_nick_tag(main_keys, access_level)
            main_part = f"{level_tag} {main_sphere_tag}" if main_sphere_tag else level_tag
            if extra_tag and access_level >= AccessLevel.ZGS and extra_tag != main_sphere_tag:
                bracket = f"[{main_part} | След. {extra_tag}]"
            else:
                bracket = f"[{main_part}]"

    result = f"{bracket} {name}"
    if len(result) > 64:
        raise ValueError("Никнейм слишком длинный (макс. 64 символа с тегами)")
    return result
