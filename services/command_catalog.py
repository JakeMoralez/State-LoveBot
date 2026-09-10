"""Catalog of bot commands that can have min_level overrides from the panel."""

from __future__ import annotations

from dataclasses import dataclass

from database.models.user import AccessLevel


@dataclass(frozen=True)
class CommandCatalogEntry:
    key: str
    label: str
    category: str
    default_min_level: int
    overridable: bool = True


COMMAND_CATALOG: tuple[CommandCatalogEntry, ...] = (
    CommandCatalogEntry("help", "Справка", "Общее", 0),
    CommandCatalogEntry("ping", "Пинг", "Общее", 0),
    CommandCatalogEntry("me", "Мой профиль", "Общее", 0),
    CommandCatalogEntry("info", "Профиль пользователя", "Общее", 0),
    CommandCatalogEntry("find", "Поиск", "Общее", 0),
    CommandCatalogEntry("getid", "ID беседы", "Общее", 0),
    CommandCatalogEntry("online", "Онлайн", "Общее", 0),
    CommandCatalogEntry("panel", "Вход на сайт", "Общее", AccessLevel.PGS),
    CommandCatalogEntry("mute", "Мут", "Беседы", AccessLevel.SUPERVISOR),
    CommandCatalogEntry("unmute", "Снять мут", "Беседы", AccessLevel.SUPERVISOR),
    CommandCatalogEntry("pin", "Закрепить", "Беседы", AccessLevel.SUPERVISOR),
    CommandCatalogEntry("unpin", "Открепить", "Беседы", AccessLevel.SUPERVISOR),
    CommandCatalogEntry("del", "Удалить сообщения", "Беседы", AccessLevel.SUPERVISOR),
    CommandCatalogEntry("stitle", "Название беседы", "Беседы", AccessLevel.ZGS),
    CommandCatalogEntry("chatsettings", "Настройки беседы", "Беседы", AccessLevel.ZGS),
    CommandCatalogEntry("rejoinkick", "Автокик при входе", "Беседы", AccessLevel.ZGS),
    CommandCatalogEntry("msg", "Оповещение", "Беседы", AccessLevel.PGS),
    CommandCatalogEntry("pools", "Список пулов", "Пулы", AccessLevel.PGS),
    CommandCatalogEntry("createpool", "Создать пул", "Пулы", AccessLevel.ZGS_GOS),
    CommandCatalogEntry("regchat", "Привязать беседу", "Пулы", AccessLevel.ZGS_GOS),
    CommandCatalogEntry("unregchat", "Отвязать беседу", "Пулы", AccessLevel.ZGS_GOS),
    CommandCatalogEntry("setlevel", "Уровень доступа", "Команда", AccessLevel.ZGS),
    CommandCatalogEntry("reg", "Назначить следящего", "Команда", AccessLevel.ZGS),
    CommandCatalogEntry("setsphere", "Сферы", "Команда", AccessLevel.ZGS),
    CommandCatalogEntry("az", "Заявка AZ", "Выдачи", AccessLevel.ZGS),
    CommandCatalogEntry("money", "Заявка виртов", "Выдачи", AccessLevel.ZGS),
    CommandCatalogEntry("academy", "Академия", "Работа", AccessLevel.PGS),
    CommandCatalogEntry("staff", "Список доступов", "Команда", AccessLevel.PGS),
    CommandCatalogEntry("panelcheck", "Кто не на сайте", "Команда", AccessLevel.ZGS),
    CommandCatalogEntry("raccess", "Снять доступы ЦА", "ЦА", AccessLevel.SUPERVISOR),
    CommandCatalogEntry("regrole", "Регистрация беседы роли", "ЦА", AccessLevel.ZGS),
    CommandCatalogEntry("setspeaker", "Спикер конгресса", "Конгресс", AccessLevel.SUPERVISOR),
    CommandCatalogEntry("setvice", "Вице-спикер", "Конгресс", AccessLevel.SUPERVISOR),
    CommandCatalogEntry("removespeaker", "Снять спикера", "Конгресс", AccessLevel.SUPERVISOR),
    CommandCatalogEntry("removevice", "Снять вице", "Конгресс", AccessLevel.SUPERVISOR),
    CommandCatalogEntry("addleader", "Назначить лидера", "Руководство", AccessLevel.SUPERVISOR),
    CommandCatalogEntry("removeleader", "Снять лидера", "Руководство", AccessLevel.SUPERVISOR),
    CommandCatalogEntry("kick", "Кик", "Беседы", AccessLevel.SUPERVISOR, overridable=False),
    CommandCatalogEntry("poolkick", "Кик из пула", "Беседы", AccessLevel.SUPERVISOR, overridable=False),
    CommandCatalogEntry("setnick", "Ник", "Команда", AccessLevel.PGS, overridable=False),
    CommandCatalogEntry(
        "forumcheck", "Проверка форума", "Разработка", AccessLevel.DEVELOPER, overridable=False
    ),
    CommandCatalogEntry(
        "syncjudges", "Синк судей", "Разработка", AccessLevel.DEVELOPER, overridable=False
    ),
)

_BY_KEY = {e.key: e for e in COMMAND_CATALOG}


def get_command_entry(key: str) -> CommandCatalogEntry | None:
    return _BY_KEY.get(key)


def catalog_payload() -> list[dict]:
    return [
        {
            "key": e.key,
            "label": e.label,
            "category": e.category,
            "default_min_level": e.default_min_level,
            "overridable": e.overridable,
        }
        for e in COMMAND_CATALOG
    ]
