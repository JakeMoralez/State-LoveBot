"""Текст /help — категории и уровни доступа (смайлик = мин. уровень)."""

from __future__ import annotations

from dataclasses import dataclass

_LEVEL_EMOJI: dict[int, str] = {
    0: "🌐",
    1: "1️⃣",
    2: "2️⃣",
    3: "3️⃣",
    4: "4️⃣",
    5: "5️⃣",
    6: "6️⃣",
    7: "7️⃣",
    8: "8️⃣",
    9: "9️⃣",
    10: "🔟",
}

_SPECIAL_EMOJI = {
    "forum": "⚖️",
}


@dataclass(frozen=True)
class HelpEntry:
    cmd: str
    desc: str
    level: int | str = 0


@dataclass(frozen=True)
class HelpCategory:
    title: str
    entries: tuple[HelpEntry, ...]


HELP_CATEGORIES: tuple[HelpCategory, ...] = (
    HelpCategory(
        "🌐 Общие",
        (
            HelpEntry("/me", "Ваш профиль"),
            HelpEntry("/getid", "ID беседы"),
            HelpEntry("/help", "Список команд"),
            HelpEntry("/ping", "Проверка бота"),
        ),
    ),
    HelpCategory(
        "👤 Профиль",
        (
            HelpEntry("/setnick", "Ник: /setnick [@user] [ник] или ответом", 1),
            HelpEntry("/who", "Карточка пользователя (ответом)", 0),
            HelpEntry("/members", "Участники беседы с никами", 0),
            HelpEntry("/staff", "Список людей с уровнями доступа", 1),
        ),
    ),
    HelpCategory(
        "🛡 Модерация",
        (
            HelpEntry("/kick", "Исключить из беседы (ответом)", 3),
            HelpEntry("/poolkick", "Исключить из всех бесед пула", 3),
            HelpEntry("/pin", "Закрепить сообщение (ответом)", 2),
            HelpEntry("/unpin", "Открепить сообщение (ответом)", 2),
            HelpEntry("/msg", "Оповещение в беседу с пингами", 2),
        ),
    ),
    HelpCategory(
        "📂 Пулы и беседы",
        (
            HelpEntry("/pools", "Список пулов и алиасов", 1),
            HelpEntry("/createpool", "Создать пул", 5),
            HelpEntry("/regchat", "Привязать беседу к пулу", 5),
            HelpEntry("/setlevel", "Выдать уровень (не выше своего)", 3),
        ),
    ),
    HelpCategory(
        "📄 Форум — раздел 3423",
        (
            HelpEntry("/info · /edit", "Инфо о теме и кнопки действий", "forum"),
            HelpEntry("/fclose · /fopen", "Закрыть / открыть тему", "forum"),
            HelpEntry("/fpin · /funpin", "Закрепить / открепить тему", "forum"),
            HelpEntry("/иски", "Статистика исков [страницы 1–20 / дни 1–365]", "forum"),
        ),
    ),
    HelpCategory(
        "⚖️ Управление судьями",
        (
            HelpEntry("/addcourt", "Назначить судью", 2),
            HelpEntry("/court", "Список судей", 3),
            HelpEntry("/regcourt", "Привязать беседу судей", 3),
            HelpEntry("/rcourt", "Снять с себя доступ судьи (кратко)", 2),
            HelpEntry("/removecourt", "Снять с себя доступ судьи (полно)", 2),
            HelpEntry("/deluser", "Удалить пользователя из БД", 10),
        ),
    ),
)


def _level_marker(level: int | str) -> str:
    if isinstance(level, str):
        return _SPECIAL_EMOJI.get(level, "•")
    return _LEVEL_EMOJI.get(level, "•")


def build_help_text() -> str:
    lines = ["📗 Команды State-LoveBot (/help):", ""]

    for category in HELP_CATEGORIES:
        lines.append(category.title)
        for entry in category.entries:
            marker = _level_marker(entry.level)
            lines.append(f"{marker} {entry.cmd} — {entry.desc}")
        lines.append("")

    lines.extend(
        [
            "🌐 — всем  ·  1️⃣–9️⃣ — мин. уровень  ·  ⚖️ — судебный доступ",
            "💡 Команды работают с / и !",
        ]
    )
    return "\n".join(lines)
