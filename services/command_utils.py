"""Двойные префиксы команд: /команда и !команда + алиасы."""

from __future__ import annotations

# primary -> короткие алиасы
COMMAND_ALIASES: dict[str, tuple[str, ...]] = {
    "setlevel": ("setlvl", "lvl"),
    "setnick": ("snick", "nick"),
    "rnick": ("removenick", "clearnick"),
    "kick": ("k",),
    "poolkick": ("pkick", "pullkick"),
    "addcourt": ("acourt",),
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
    "setca": ("adostupca", "dostupca", "caaccess"),
    "raccess": ("rrole",),
    "removecourt": ("rcourt",),
    "unregchat": ("unlinkchat", "delchat", "unpool"),
    "setspeaker": ("speaker",),
    "setvice": ("vice",),
    "removespeaker": ("rmspeaker",),
    "removevice": ("rmvice",),
    "find": ("search", "f"),
    "rejoinkick": ("rjkick",),
    "chatsettings": ("csettings", "chcfg"),
}


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
    """Голая /cmd + /cmd <args> — для одного хендлера на всё (как /addcourt)."""
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
    t = (text or "").strip().lower()
    for cmd in cmd_names(name):
        for prefix in (f"/{cmd.lower()}", f"!{cmd.lower()}"):
            if t == prefix or t.startswith(f"{prefix} "):
                return True
    return False


def strip_cmd(text: str, name: str) -> str:
    raw = (text or "").strip()
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
