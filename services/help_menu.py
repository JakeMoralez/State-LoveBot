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
    "ca": "🏛",
}


@dataclass(frozen=True)
class HelpEntry:
    cmd: str
    desc: str
    level: int | str = 0
    ca: bool = False


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
            HelpEntry("/find", "Поиск по нику или VK", 0),
            HelpEntry("/reg", "Дата регистрации VK", 0),
            HelpEntry("/online", "Кто онлайн в беседе", 0),
            HelpEntry("/help", "Список команд"),
            HelpEntry("/ping", "Проверка бота"),
        ),
    ),
    HelpCategory(
        "👤 Профиль",
        (
            HelpEntry("/setnick", "Установить ник [@user] [ник]", 1),
            HelpEntry("/who", "Карточка пользователя", 0),
            HelpEntry("/members", "Участники беседы", 0),
            HelpEntry("/staff", "Список доступов и ролей", 1),
        ),
    ),
    HelpCategory(
        "🛡 Модерация",
        (
            HelpEntry("/kick", "Исключить из беседы", 3),
            HelpEntry("/poolkick", "Исключить из всех бесед пула", 3),
            HelpEntry("/mute", "Мут [@user] [время] [причина]", 2),
            HelpEntry("/unmute", "Снять мут", 2),
            HelpEntry("/stitle", "Название беседы", 3),
            HelpEntry("/pin", "Закрепить сообщение", 2),
            HelpEntry("/unpin", "Открепить сообщение", 2),
            HelpEntry("/del", "Удалить сообщение", 2),
            HelpEntry("/msg", "Оповещение в беседу", 2),
            HelpEntry("/chatsettings", "Настройки беседы", 3),
            HelpEntry("/rejoinkick", "Автокик при выходе: on / ask", 3),
        ),
    ),
    HelpCategory(
        "📂 Пулы и беседы",
        (
            HelpEntry("/pools", "Список пулов", 1),
            HelpEntry("/createpool", "Создать пул", 5),
            HelpEntry("/regchat", "Привязать беседу к пулу", 5),
            HelpEntry("/unregchat", "Отвязать беседу от пула", 5),
            HelpEntry("/setlevel", "Уровень [@user] [0–8]", 3),
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
        "🏛 ЦА",
        (
            HelpEntry("/setca", "Выдать или снять доступ ЦА [@user] [off]", 3, ca=True),
            HelpEntry("/raccess", "Снять роли с пользователя [@user]", 3, ca=True),
            HelpEntry(
                "/regrole",
                "Привязать беседу: court, congress, sledca",
                3,
                ca=True,
            ),
        ),
    ),
    HelpCategory(
        "🏛 Конгресс",
        (
            HelpEntry("/setspeaker", "Назначить спикера", 3, ca=True),
            HelpEntry("/setvice", "Назначить вице-спикера", 3, ca=True),
            HelpEntry("/congress", "Инфо о конгрессе", 1, ca=True),
            HelpEntry("/removespeaker", "Снять спикера", 3, ca=True),
            HelpEntry("/removevice", "Снять вице-спикера", 3, ca=True),
        ),
    ),
    HelpCategory(
        "⚖️ Судьи",
        (
            HelpEntry("/addcourt", "Назначить судью", 2, ca=True),
            HelpEntry("/court", "Список судей", 3, ca=True),
            HelpEntry("/deluser", "Удалить пользователя из БД", 10),
        ),
    ),
)


def _level_marker(entry: HelpEntry) -> str:
    if isinstance(entry.level, str):
        return _SPECIAL_EMOJI.get(entry.level, "•")
    base = _LEVEL_EMOJI.get(entry.level, "•")
    if entry.ca:
        return f"{base}🏛"
    return base


def build_help_text() -> str:
    lines = ["📗 Команды State-LoveBot", ""]

    for category in HELP_CATEGORIES:
        lines.append(category.title)
        for entry in category.entries:
            marker = _level_marker(entry)
            lines.append(f"{marker} {entry.cmd} — {entry.desc}")
        lines.append("")

    lines.extend(
        [
            "🌐 — всем  ·  1️⃣–9️⃣ — мин. уровень  ·  🏛 — доступ ЦА (ур. 1–4)",
            "⚖️ — судебный доступ к форуму  ·  / и !",
        ]
    )
    return "\n".join(lines)
