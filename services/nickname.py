"""Валидация системных никнеймов (/snick)."""

from __future__ import annotations

import re

BANNED_SUBSTRINGS = (
    "admin",
    "moder",
    "fuck",
    "shit",
    "сука",
    "бля",
    "хуй",
    "пизд",
)

FACTION_TAGS: frozenset[str] = frozenset(
    {
        "GOV",
        "LC",
        "FBI",
        "LSPD",
        "RCSD",
        "SFPD",
        "SWAT",
        "LSa",
        "SFa",
        "FP",
        "LSMC",
        "LVMC",
        "SFFD",
        "CNN LS",
    }
)

CONGRESS_ROLES: frozenset[str] = frozenset(
    {
        "Speaker",
        "Vice-Speaker",
        "Congressman",
    }
)

JUDGE_ROLE = "Judge"

MINISTER_TAGS: frozenset[str] = frozenset(
    {
        "Pr.Min",
        "Min.Just",
        "Min.Nat.Sec",
        "Min.Soc",
        "Ad.Pr.Min",
        "Ad.Min.Just",
        "Ad.Min.Nat.Sec",
        "Ad.Min.Soc",
    }
)

_NAME_RE = re.compile(r"^[A-Z][A-Za-z0-9]*_[A-Z][A-Za-z0-9]*$")
_TAG_CHUNK_RE = re.compile(r"^\[([^\]]+)\]")
_RANK_RE = re.compile(r"^\[(9|10)\]\s*")

_FORMAT_HINT = (
    "Формат: [фракция] [9|10] Name_Surname\n"
    "Или: [Speaker] / [Speaker | LSPD][10] Name_Surname\n"
    "Или: [Judge] Name_Surname\n"
    "Или: [Pr.Min] Name_Surname"
)


def _ascii_brackets(text: str) -> str:
    return text.replace("［", "[").replace("］", "]").replace("｜", "|")


def _check_banned(nickname: str) -> str | None:
    lower = nickname.lower()
    for banned in BANNED_SUBSTRINGS:
        if banned in lower:
            return "Никнейм содержит запрещённые слова."
    return None


def _validate_name(name: str) -> str | None:
    if not name:
        return "Укажите имя: Name_Surname"
    if " " in name:
        return "В имени не должно быть пробелов. Формат: Name_Surname"
    if not _NAME_RE.match(name):
        return "Имя: Name_Surname (латиница, одно подчёркивание)"
    return None


def _canon_faction(raw: str) -> str | None:
    cleaned = " ".join(raw.split())
    for tag in FACTION_TAGS:
        if cleaned.casefold() == tag.casefold():
            return tag
    return None


def _canon_congress_role(raw: str) -> str | None:
    cleaned = raw.strip()
    if cleaned.casefold() == JUDGE_ROLE.casefold():
        return JUDGE_ROLE
    for role in CONGRESS_ROLES:
        if cleaned.casefold() == role.casefold():
            return role
    return None


def _canon_minister(raw: str) -> str | None:
    cleaned = raw.strip()
    for tag in MINISTER_TAGS:
        if cleaned.casefold() == tag.casefold():
            return tag
    return None


class NicknameValidator:
    @staticmethod
    def validate(nickname: str) -> tuple[bool, str]:
        """Совместимость: (ok, error). Нормализованный ник — через normalize()."""
        _normalized, err = NicknameValidator.normalize(nickname)
        if err:
            return False, err
        return True, ""

    @staticmethod
    def normalize(nickname: str) -> tuple[str | None, str | None]:
        """Вернуть (нормализованный_ник, ошибка)."""
        raw = _ascii_brackets((nickname or "").strip())
        if not raw:
            return None, "Никнейм не может быть пустым."
        if len(raw) > 64:
            return None, "Никнейм слишком длинный (макс. 64 символа)."

        banned = _check_banned(raw)
        if banned:
            return None, banned

        if not raw.startswith("["):
            return None, f"Ник должен начинаться с тега в [].\n{_FORMAT_HINT}"

        m_tag = _TAG_CHUNK_RE.match(raw)
        if not m_tag:
            return None, f"Некорректные скобки тега.\n{_FORMAT_HINT}"

        first_inner = m_tag.group(1).strip()
        rest_after_first = raw[m_tag.end() :].lstrip()

        minister = _canon_minister(first_inner)
        if minister is not None:
            if rest_after_first.startswith("["):
                return None, "У министров ранг не указывается."
            name_err = _validate_name(rest_after_first)
            if name_err:
                return None, name_err
            return f"[{minister}] {rest_after_first}", None

        if "|" in first_inner:
            left, _, right = first_inner.partition("|")
            role = _canon_congress_role(left.strip())
            faction = _canon_faction(right.strip())
            if role is None:
                return None, "Роль: Speaker, Vice-Speaker или Congressman."
            if role == JUDGE_ROLE:
                return None, "Judge — только [Judge] Name_Surname, без фракции и ранга."
            if faction is None:
                return None, "После | укажите фракцию из списка (GOV, LSPD, …)."
            rank_m = _RANK_RE.match(rest_after_first)
            if not rank_m:
                return None, "С фракцией нужен ранг: [9] или [10]."
            rank = rank_m.group(1)
            name = rest_after_first[rank_m.end() :].strip()
            name_err = _validate_name(name)
            if name_err:
                return None, name_err
            return f"[{role} | {faction}][{rank}] {name}", None

        congress_role = _canon_congress_role(first_inner)
        if congress_role is not None:
            if rest_after_first.startswith("["):
                return None, (
                    "Без фракции ранг не нужен.\n"
                    "С фракцией: [Speaker | LSPD][10] Name_Surname"
                )
            name_err = _validate_name(rest_after_first)
            if name_err:
                return None, name_err
            return f"[{congress_role}] {rest_after_first}", None

        faction = _canon_faction(first_inner)
        if faction is None:
            return None, (
                "Неизвестный тег. Используйте фракцию, Speaker/Vice-Speaker/"
                f"Congressman/Judge или тег министра.\n{_FORMAT_HINT}"
            )

        rank_m = _RANK_RE.match(rest_after_first)
        if not rank_m:
            return None, "После фракции нужен ранг: [9] или [10]."
        rank = rank_m.group(1)
        name = rest_after_first[rank_m.end() :].strip()
        name_err = _validate_name(name)
        if name_err:
            return None, name_err
        return f"[{faction}] [{rank}] {name}", None
