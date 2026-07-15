"""Двойные префиксы команд: /команда и !команда + алиасы."""

from __future__ import annotations

import re

# primary -> короткие алиасы
COMMAND_ALIASES: dict[str, tuple[str, ...]] = {
    "setlevel": ("setlvl", "lvl"),
    "setnick": ("snick", "nick"),
    "rnick": ("removenick", "clearnick"),
    "kick": ("k",),
    "poolkick": ("pkick", "pullkick"),
    "addleader": ("aleader",),
    "removeleader": ("rleader",),
    "leaders": ("leaderlist",),
    "deluser": ("du",),
    "members": ("mems", "member", "nlist", "nicklist"),
    "regchat": ("rchat",),
    "devhelp": ("dhelp",),
    "meserver": ("mserver", "myserver"),
    "setserver": ("sserver", "servercfg"),
    "createpool": ("cpool",),
    "staff": ("access", "accesses"),
    "court": ("judges",),
    "msg": ("notify",),
    "pools": ("pool",),
    "regcongress": ("regcong",),
    "regrole": ("regcourt", "regsledco", "regsledca"),
    "raccess": ("rrole",),
    "fclose": ("fclosed",),
    "fopen": ("fopened",),
    "fresolve": ("resolve", "fcloseunpin"),
    "form": ("addform",),
    "forms": ("listforms", "pendingforms"),
    "formsid": ("forms_id",),
    "myform": ("myforms",),
    "acceptform": ("formaccept", "aform"),
    "rejectform": ("formreject", "rform"),
    "unregchat": ("unlinkchat", "delchat", "unpool"),
    "setspeaker": ("speaker",),
    "setvice": ("vice",),
    "removespeaker": ("rmspeaker",),
    "removevice": ("rmvice",),
    "find": ("search", "f"),
    "rejoinkick": ("rjkick",),
    "chatsettings": ("csettings", "chcfg"),
    "forumcheck": ("fcheck", "forumstatus"),
    "syncjudges": ("courtupdate",),
    "claimfill": ("fillclaims", "courtstatfill"),
    "panel": ("login",),
    "editmydiscord": ("mydiscord", "discordid", "dsid"),
    "editmyforum": ("myforum", "forumid", "forumlink"),
}


_VK_MENTION_PREFIX = re.compile(r"^\[(?:id|club)\d+\|[^\]]+\]\s*", re.IGNORECASE)


def normalize_message_text(text: str) -> str:
    """Убрать префикс @упоминания бота в беседах ([club…|@name] /cmd)."""
    t = (text or "").strip()
    while True:
        m = _VK_MENTION_PREFIX.match(t)
        if not m:
            break
        t = t[m.end() :].strip()
    return t


def cmd_names(name: str) -> tuple[str, ...]:
    return (name,) + COMMAND_ALIASES.get(name, ())


def dual(name: str) -> list[str]:
    patterns: list[str] = []
    for n in cmd_names(name):
        patterns.extend((f"/{n}", f"!{n}"))
    return patterns


def dual_with_args(name: str, args: str) -> list[str]:
    """Только /cmd <args> — для пар с отдельным dual() usage-хендлером."""
    patterns: list[str] = []
    for n in cmd_names(name):
        patterns.extend((f"/{n} {args}", f"!{n} {args}"))
    return patterns


def dual_args(name: str, args: str = "<args>") -> list[str]:
    """Голая /cmd + /cmd <args> — для одного хендлера на всё."""
    patterns: list[str] = []
    for n in cmd_names(name):
        patterns.extend(
            (
                f"/{n}",
                f"!{n}",
                f"/{n} {args}",
                f"!{n} {args}",
            )
        )
    return patterns


def matches_cmd(text: str, name: str) -> bool:
    t = normalize_message_text(text).lower()
    for cmd in cmd_names(name):
        for prefix in (f"/{cmd.lower()}", f"!{cmd.lower()}"):
            if t == prefix or t.startswith(f"{prefix} "):
                return True
    return False


def matches_who(text: str) -> bool:
    """/who, !who, кто — без учёта регистра."""
    t = (text or "").strip()
    if not t:
        return False
    if t.casefold() == "кто":
        return True
    return matches_cmd(t, "who")


def strip_cmd(text: str, name: str) -> str:
    raw = normalize_message_text(text)
    prefixes: list[str] = []
    for cmd in cmd_names(name):
        prefixes.extend((f"/{cmd}", f"!{cmd}"))
    prefixes.sort(key=len, reverse=True)
    lower = raw.lower()
    for prefix in prefixes:
        if lower.startswith(prefix.lower()):
            return raw[len(prefix) :].strip()
    return raw


def parse_forum_thread(text: str, names: tuple[str, ...]) -> int | None:
    from services.forum_api import ForumService

    for name in names:
        for cmd in cmd_names(name):
            for prefix in (f"!{cmd}", f"/{cmd}"):
                thread_id, _ = ForumService.parse_forum_command(text, prefix)
                if thread_id:
                    return thread_id
    return None


def is_user_info_cmd(text: str) -> bool:
    """`/info` для профиля (не тема форума)."""
    raw = text or ""
    if not matches_cmd(raw, "info"):
        return False
    return parse_forum_thread(raw, ("info",)) is None
