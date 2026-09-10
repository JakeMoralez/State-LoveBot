"""Заявки на выдачу AZ / виртов через панель."""

from __future__ import annotations

import re

from vkbottle import API
from vkbottle.bot import Bot, Message
from vkbottle.dispatch.rules.base import FuncRule

from database.models.user import AccessLevel
from middlewares.access import requires_level
from middlewares.action_logger import ActionLogger
from services import responses as resp
from services.command_utils import matches_cmd, strip_cmd
from services.panel_client import create_issuance, panel_api_configured

_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)

_USAGE_AZ = "/az Ник 5000 Должность | За что"
_USAGE_VIRTS = "/money Ник 70000000 Должность | За что"


def _usage(kind: str) -> str:
    return _USAGE_AZ if kind == "az" else _USAGE_VIRTS


def parse_issuance_args(raw: str) -> tuple[str, str, str, str, str] | None:
    """ник, сумма, должность, причина, ссылка — или None."""
    text = (raw or "").strip()
    if not text:
        return None
    proof = ""
    urls = _URL_RE.findall(text)
    if urls:
        proof = urls[-1].rstrip(").,;")
        text = text.replace(urls[-1], " ", 1).strip()
        text = re.sub(r"\s+", " ", text)

    if "|" in text:
        left, right = text.split("|", 1)
        tokens = left.split()
        reason = right.strip()
        if len(tokens) < 3 or not reason:
            return None
        nick, amount, *role_parts = tokens
        role = " ".join(role_parts).strip()
        if not role:
            return None
        return nick, amount, role, reason, proof

    tokens = text.split()
    if len(tokens) < 4:
        return None
    nick, amount, role, *reason_parts = tokens
    reason = " ".join(reason_parts).strip()
    if not reason:
        return None
    return nick, amount, role, reason, proof


def register_issuance(bot: Bot, api: API, action_logger: ActionLogger) -> None:
    del api, action_logger

    @bot.on.message(
        FuncRule(
            lambda m: matches_cmd(m.text or "", "az") or matches_cmd(m.text or "", "money")
        )
    )
    @requires_level(AccessLevel.ZGS)
    async def issuance_cmd(message: Message, server_id: int = 0, access_level: int = 0):
        text = message.text or ""
        kind = "az" if matches_cmd(text, "az") else "virts"
        primary = "az" if kind == "az" else "money"
        from services.command_access import effective_min_level
        from middlewares.access import AccessChecker

        need = await effective_min_level(server_id, primary, AccessLevel.ZGS)
        if access_level < need:
            await message.answer(
                resp.denied(
                    "Недостаточно прав для этой команды.",
                    hint=(
                        f"Нужен уровень: {AccessChecker.level_name(need)}\n"
                        f"Ваш уровень: {AccessChecker.level_name(access_level)}"
                    ),
                )
            )
            return
        parsed = parse_issuance_args(strip_cmd(text, primary))
        if not parsed:
            await message.answer(resp.error("Не хватает данных.", hint=_usage(kind)))
            return
        if not panel_api_configured():
            await message.answer(resp.error("Панель выдач не настроена."))
            return
        nick, amount, role, reason, proof = parsed
        ok, data = await create_issuance(
            message.from_id,
            server_id,
            kind=kind,
            nickname=nick,
            amount=amount,
            role_title=role,
            reason=reason,
            proof_url=proof,
        )
        if not ok:
            await message.answer(resp.error(str(data)))
            return
        item = data.get("item") if isinstance(data, dict) else None
        label = item.get("amount_label") if isinstance(item, dict) else amount
        action = "передачу" if kind == "az" else "выдачу"
        await message.answer(
            resp.success(
                f"Заявка на {action} отправлена: {nick} · {label}.",
                hint="Проверить можно на сайте в разделе «Выдачи».",
            )
        )
