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
            HelpEntry("/ping", "Проверка бота и время работы"),
        ),
    ),
    HelpCategory(
        "👤 Профиль",
        (
            HelpEntry("/setnick", "Установить ник [@user] [ник]", 1),
            HelpEntry("/rnick", "Снять ник [@user]", 1),
            HelpEntry("/who", "Карточка пользователя", 0),
            HelpEntry("/members", "Участники беседы", 0),
            HelpEntry("/staff", "Список доступов и ролей", 1),
            HelpEntry(
                "/editmydiscord",
                "Привязать Discord ID для входа на сайт",
                0,
                ca=True,
            ),
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
        "📄 Форум — раздел судебных исков сервера",
        (
            HelpEntry("/info · /edit", "Инфо о теме и кнопки действий", "forum"),
            HelpEntry("/fclose · /fopen", "Закрыть / открыть тему (алиасы: fclosed, fopened)", "forum"),
            HelpEntry("/fpin · /funpin", "Закрепить / открепить тему", "forum"),
            HelpEntry("/fresolve", "Закрыть тему и открепить (алиас: resolve)", "forum"),
            HelpEntry("/иски", "Статистика исков [страницы 1–20 / дни 1–365]", "forum"),
            HelpEntry("/form", "Отправить игровые формы (судья)", "forum"),
            HelpEntry("/myform", "Ваши формы и статусы", "forum"),
            HelpEntry("/forms", "Команды для игры (без #id)", 2, ca=True),
            HelpEntry("/forms id · /formsid", "С #id каждой формы", 2, ca=True),
            HelpEntry(
                "/acceptform · /rejectform",
                "Принять / отклонить [id|all]",
                2,
                ca=True,
            ),
        ),
    ),
    HelpCategory(
        "🏛 ЦА",
        (
            HelpEntry("/setca", "Выдать или снять доступ ЦА [@user] [off]", 3, ca=True),
            HelpEntry("/raccess", "Снять роли с пользователя [@user]", 2, ca=True),
            HelpEntry(
                "/regrole",
                "Привязать беседу: court, congress, sledca, leader",
                3,
                ca=True,
            ),
            HelpEntry(
                "/panel",
                "Вход на сайт след. ЦА (если нет Discord)",
                0,
                ca=True,
            ),
        ),
    ),
    HelpCategory(
        "🏛 Конгресс",
        (
            HelpEntry("/setspeaker", "Назначить спикера", 2, ca=True),
            HelpEntry("/setvice", "Назначить вице-спикера", 2, ca=True),
            HelpEntry("/congress", "Инфо о конгрессе", 0),
            HelpEntry("/removespeaker", "Снять спикера", 2, ca=True),
            HelpEntry("/removevice", "Снять вице-спикера", 2, ca=True),
        ),
    ),
    HelpCategory(
        "⚖️ Судьи",
        (
            HelpEntry("/addcourt", "Назначить судью", 2, ca=True),
            HelpEntry("/removecourt", "Снять судью [@user]", 2, ca=True),
            HelpEntry("/court", "Список судей", 0),
        ),
    ),
    HelpCategory(
        "🛡 Лидеры",
        (
            HelpEntry("/addleader", "Лидер для панели [@user] [фракция]", 2, ca=True),
            HelpEntry("/removeleader", "Снять лидера [@user]", 2, ca=True),
            HelpEntry("/leaders", "Список лидеров (панель)", 0),
        ),
    ),
)

DEV_HELP_CATEGORIES: tuple[HelpCategory, ...] = (
    HelpCategory(
        "🔟 Разработчик",
        (
            HelpEntry("/devhelp", "Справка для ур. 10"),
            HelpEntry("/meserver", "Переключить активный server_id", 10),
            HelpEntry("/setserver", "Тег, раздел исков, имя сервера", 10),
            HelpEntry("/regchat logs", "Беседа для логов бота", 10),
            HelpEntry("/regchat logs off", "Отвязать беседу логов", 10),
            HelpEntry("/deluser", "Удалить пользователя из БД", 10),
            HelpEntry("/forumcheck", "Проверка сессии форума", 10),
            HelpEntry("/forumcheck reconnect", "Переподключить форум (.env)", 10),
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


def _format_categories(categories: tuple[HelpCategory, ...], *, header: str) -> str:
    lines = [header, ""]

    for category in categories:
        lines.append(category.title)
        for entry in category.entries:
            marker = _level_marker(entry)
            lines.append(f"{marker} {entry.cmd} — {entry.desc}")
        lines.append("")

    return "\n".join(lines)


def build_help_text() -> str:
    body = _format_categories(HELP_CATEGORIES, header="📗 Команды State-LoveBot")
    return (
        f"{body}"
        "🌐 — всем  ·  1️⃣–9️⃣ — мин. уровень  ·  🏛 — доступ ЦА (ур. 1–4)\n"
        "⚖️ — судебный доступ к форуму  ·  / и !"
    )


def build_dev_help_text() -> str:
    body = _format_categories(DEV_HELP_CATEGORIES, header="🛠 Dev-команды (ур. 10)")
    return f"{body}🔟 — только разработчик  ·  / и !"
