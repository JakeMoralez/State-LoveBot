"""Валидация системных никнеймов."""

from __future__ import annotations

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


class NicknameValidator:
    @staticmethod
    def validate(nickname: str) -> tuple[bool, str]:
        nickname = nickname.strip()
        if not nickname:
            return False, "Никнейм не может быть пустым."
        if len(nickname) > 64:
            return False, "Никнейм слишком длинный (макс. 64 символа)."
        lower = nickname.lower()
        for banned in BANNED_SUBSTRINGS:
            if banned in lower:
                return False, "Никнейм содержит запрещённые слова."
        return True, ""
