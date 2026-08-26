"""Текст /help — категории и уровни доступа (смайлик = мин. уровень)."""

from __future__ import annotations

from dataclasses import dataclass

from database.models.user import AccessLevel
from database.repository.forum_role_repo import ForumRoleRepository
from database.repository.user_repo import UserRepository
from middlewares.ca_access import can_review_court_forms
from middlewares.forum_access import ForumAccessChecker

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
    10: "🅰️",
    11: "🔟",
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
    public: bool = False
    judge_only: bool = False
    ca_forms: bool = False


@dataclass
class HelpContext:
    access_level: int
    bot_access: bool
    ca_scope: bool
    is_developer: bool
    is_judge: bool
    can_review_forms: bool
    can_manage_court: bool


@dataclass(frozen=True)
class HelpCategory:
    title: str
    entries: tuple[HelpEntry, ...]


HELP_CATEGORIES: tuple[HelpCategory, ...] = (
    HelpCategory(
        "🌐 Общие",
        (
            HelpEntry("/me", "Ваш профиль", public=True),
            HelpEntry("/info", "Профиль пользователя", public=True),
            HelpEntry("/panel", "Вход на сайт", 1),
            HelpEntry("/getid", "ID беседы", public=True),
            HelpEntry("/find", "Поиск по нику или VK", public=True),
            HelpEntry("/regdate", "Дата регистрации VK", public=True),
            HelpEntry("/online", "Кто онлайн в беседе", public=True),
            HelpEntry("/help", "Список команд", public=True),
            HelpEntry("/ping", "Проверка бота", public=True),
        ),
    ),
    HelpCategory(
        "👤 Профиль",
        (
            HelpEntry("/setnick", "[фракция] [9|10] Name_Surname", 1),
            HelpEntry("/rnick", "Снять ник", 1),
            HelpEntry("/who", "Карточка пользователя", public=True),
            HelpEntry("/members", "Участники беседы", public=True),
            HelpEntry("/staff", "Список доступов и ролей", 1),
            HelpEntry("/setsphere", "Назначить сферы", AccessLevel.ZGS),
            HelpEntry("/editmydiscord", "Привязать Discord", public=True),
            HelpEntry("/editmyforum", "Привязать форум", public=True),
        ),
    ),
    HelpCategory(
        "🛡 Модерация",
        (
            HelpEntry("/kick", "Исключить из беседы", AccessLevel.SUPERVISOR),
            HelpEntry("/poolkick", "Исключить из бесед пула", AccessLevel.SUPERVISOR),
            HelpEntry("/mute", "Выдать мут", 2),
            HelpEntry("/unmute", "Снять мут", 2),
            HelpEntry("/stitle", "Название беседы", 3),
            HelpEntry("/pin", "Закрепить сообщение", 2),
            HelpEntry("/unpin", "Открепить сообщение", 2),
            HelpEntry("/del", "Удалить сообщение", 2),
            HelpEntry("/msg", "Оповещение в беседу", 1),
            HelpEntry("/chatsettings", "Настройки беседы", 3),
            HelpEntry("/rejoinkick", "Автокик при повторном входе", 3),
        ),
    ),
    HelpCategory(
        "📂 Пулы и беседы",
        (
            HelpEntry("/pools", "Список пулов", 1),
            HelpEntry("/createpool", "Создать пул", AccessLevel.ZGS_GOS),
            HelpEntry("/regchat", "Привязать беседу к пулу", AccessLevel.ZGS_GOS),
            HelpEntry("/unregchat", "Отвязать беседу от пула", AccessLevel.ZGS_GOS),
            HelpEntry("/setlevel", "Изменить уровень доступа", AccessLevel.ZGS),
            HelpEntry("/reg", "Назначить следящего", AccessLevel.ZGS),
        ),
    ),
    HelpCategory(
        "📄 Форум — судебные иски",
        (
            HelpEntry("/info · /edit", "Инфо и действия по теме", "forum"),
            HelpEntry("/fclose · /fopen", "Закрыть / открыть тему", "forum"),
            HelpEntry("/fpin · /funpin", "Закрепить / открепить тему", "forum"),
            HelpEntry("/fresolve", "Закрыть и открепить тему", "forum"),
            HelpEntry("/иски", "Статистика закрытий", "forum"),
            HelpEntry("/form", "Отправить игровые формы", "forum", judge_only=True),
            HelpEntry("/myform", "Ваши формы", "forum", judge_only=True),
            HelpEntry("/forms", "Список форм", 2, ca=True, ca_forms=True),
            HelpEntry("/forms id", "Список форм с id", 2, ca=True, ca_forms=True),
            HelpEntry(
                "/acceptform · /rejectform",
                "Принять / отклонить форму",
                2,
                ca=True,
                ca_forms=True,
            ),
        ),
    ),
    HelpCategory(
        "🏛 ЦА",
        (
            HelpEntry("/raccess", "Снять роли с пользователя", 2, ca=True),
            HelpEntry("/regrole", "Привязать роль к беседе", 3, ca=True),
        ),
    ),
    HelpCategory(
        "🏛 Конгресс",
        (
            HelpEntry("/setspeaker", "Назначить спикера", 2, ca=True),
            HelpEntry("/setvice", "Назначить вице-спикера", 2, ca=True),
            HelpEntry("/congress", "Инфо о конгрессе", public=True),
            HelpEntry("/removespeaker", "Снять спикера", 2, ca=True),
            HelpEntry("/removevice", "Снять вице-спикера", 2, ca=True),
        ),
    ),
    HelpCategory(
        "⚖️ Судьи",
        (
            HelpEntry("/court", "Список судей", public=True),
        ),
    ),
)

DEV_HELP_CATEGORIES: tuple[HelpCategory, ...] = (
    HelpCategory(
        "🔟 Разработчик",
        (
            HelpEntry("/devhelp", "Справка разработчика"),
            HelpEntry("/meserver", "Переключить сервер", AccessLevel.DEVELOPER),
            HelpEntry("/setserver", "Настройки сервера", AccessLevel.DEVELOPER),
            HelpEntry("/regchat logs", "Беседа для логов", AccessLevel.DEVELOPER),
            HelpEntry("/regchat logs off", "Отвязать беседу логов", AccessLevel.DEVELOPER),
            HelpEntry("/deluser", "Удалить пользователя", AccessLevel.DEVELOPER),
            HelpEntry("/forumcheck", "Проверка сессии форума", AccessLevel.DEVELOPER),
            HelpEntry("/forumcheck reconnect", "Переподключить форум", AccessLevel.DEVELOPER),
            HelpEntry("/syncjudges", "Обновить список судей", AccessLevel.DEVELOPER),
            HelpEntry("/claimfill", "Дозаписать закрытые иски", AccessLevel.DEVELOPER),
            HelpEntry("/claimwatch", "Проверить новые иски", AccessLevel.DEVELOPER),
            HelpEntry("/complaintwatch", "Проверить жалобы на лидеров", AccessLevel.DEVELOPER),
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


def _format_categories(
    categories: tuple[HelpCategory, ...],
    *,
    header: str,
    visible: set[tuple[str, str]] | None = None,
) -> str:
    lines = [header, ""]

    for category in categories:
        shown: list[HelpEntry] = []
        for entry in category.entries:
            if visible is not None and (category.title, entry.cmd) not in visible:
                continue
            shown.append(entry)
        if not shown:
            continue

        lines.append(category.title)
        for entry in shown:
            marker = _level_marker(entry)
            lines.append(f"{marker} {entry.cmd} — {entry.desc}")
        lines.append("")

    return "\n".join(lines)


async def build_help_context(user_id: int, server_id: int) -> HelpContext:
    access_level = await UserRepository.get_access_level(user_id, server_id)
    return HelpContext(
        access_level=access_level,
        bot_access=await ForumRoleRepository.can_use_forum_bot(user_id),
        ca_scope=await UserRepository.can_use_ca_scope(user_id, server_id),
        is_developer=await UserRepository.is_developer(user_id),
        is_judge=await ForumRoleRepository.is_judge_effective(user_id, server_id),
        can_review_forms=await can_review_court_forms(user_id, server_id),
        can_manage_court=await ForumAccessChecker.can_manage_court_roles(
            user_id,
            server_id,
        ),
    )


def _entry_visible(entry: HelpEntry, ctx: HelpContext) -> bool:
    if ctx.is_developer:
        return True

    if entry.ca and not ctx.ca_scope:
        return False

    if entry.ca_forms and not ctx.can_review_forms:
        return False

    if entry.judge_only and not ctx.is_judge:
        return False

    if entry.public:
        return True

    if not ctx.bot_access:
        return False

    if isinstance(entry.level, str):
        if entry.level != "forum":
            return False
        if entry.judge_only:
            return ctx.is_judge
        if entry.ca_forms:
            return ctx.can_review_forms
        return True

    return ctx.access_level >= entry.level


async def build_help_text_for_user(user_id: int, server_id: int) -> str:
    ctx = await build_help_context(user_id, server_id)
    visible: set[tuple[str, str]] = set()
    for category in HELP_CATEGORIES:
        for entry in category.entries:
            if _entry_visible(entry, ctx):
                visible.add((category.title, entry.cmd))

    level_name = (
        AccessLevel.title(ctx.access_level)
        if ctx.access_level
        else "нет доступа"
    )
    header = f"📗 Команды\n👤 Уровень: {level_name}"
    body = _format_categories(HELP_CATEGORIES, header=header, visible=visible)
    if not visible:
        body = (
            f"{header}\n\n"
            "⛔ Нет доступных команд.\n"
            "Обратитесь к администратору."
        )
    return (
        f"{body}"
        "🌐 — всем  ·  1️⃣–9️⃣ — мин. уровень  ·  🏛 — ЦА  ·  ⚖️ — форум\n"
        "Префикс: / или !"
    )


def build_dev_help_text() -> str:
    body = _format_categories(
        DEV_HELP_CATEGORIES,
        header="🛠 Команды разработчика",
    )
    return f"{body}🔟 — только разработчик"
