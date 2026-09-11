"""Уведомления в беседу «Управляющие» о заявках на выдачу."""

from __future__ import annotations

import logging

from vkbottle import API, Keyboard, OpenLink

from database.models.chat_kind import ChatKind
from services.chat_kind import list_kind_peers
from services.panel_login import PANEL_BASE_URL

logger = logging.getLogger(__name__)


def _kind_title(kind: str) -> str:
    if kind == "az":
        return "передачу AZ"
    return "выдачу виртов"


def _panel_issuance_url(kind: str) -> str:
    base = (PANEL_BASE_URL or "").rstrip("/")
    tab = "az" if kind == "az" else "virts"
    if not base:
        return ""
    return f"{base}/issuance?kind={tab}"


def _build_message(payload: dict) -> str:
    kind = str(payload.get("kind") or "virts")
    lines = [
        f"📥 Поступил запрос на {_kind_title(kind)}",
        "",
        "Детали",
        f"• Ник: {payload.get('nickname') or '—'}",
        f"• Сумма: {payload.get('amount_label') or payload.get('amount') or '—'}",
        f"• Должность: {payload.get('role_title') or '—'}",
        f"• Причина: {payload.get('reason') or '—'}",
    ]
    who = (payload.get("created_by_name") or "").strip()
    if not who and payload.get("created_by_vk_id"):
        who = f"id{payload['created_by_vk_id']}"
    if who:
        lines.append(f"• От: {who}")
    proof = (payload.get("proof_url") or "").strip()
    if proof:
        lines.append(f"• Доказательство: {proof}")
    return "\n".join(lines)


def _keyboard(kind: str) -> str | None:
    url = _panel_issuance_url(kind)
    if not url:
        return None
    kb = Keyboard(inline=True)
    kb.add(OpenLink(link=url, label="Открыть на сайте"))
    return kb.get_json()


async def notify_managers_issuance(api: API, payload: dict) -> dict:
    """Разослать заявку во все беседы типа «Управляющие» на сервере."""
    try:
        server_id = int(payload.get("server_id") or 0)
    except (TypeError, ValueError):
        server_id = 0
    if not server_id:
        return {"ok": False, "error": "server_id required", "sent": 0}

    peers = await list_kind_peers(server_id, ChatKind.MANAGERS)
    if not peers:
        logger.info("issuance notify: no managers chats server=%s", server_id)
        return {"ok": True, "sent": 0, "peers": []}

    text = _build_message(payload)
    keyboard = _keyboard(str(payload.get("kind") or "virts"))
    sent: list[int] = []
    errors: list[str] = []
    for peer_id in peers:
        try:
            params: dict = {
                "peer_id": peer_id,
                "message": text,
                "random_id": 0,
                "disable_mentions": 1,
            }
            if keyboard:
                params["keyboard"] = keyboard
            await api.messages.send(**params)
            sent.append(peer_id)
        except Exception as exc:
            logger.warning(
                "issuance notify failed peer=%s server=%s: %s",
                peer_id,
                server_id,
                exc,
            )
            errors.append(f"{peer_id}: {exc}")
    return {"ok": True, "sent": len(sent), "peers": sent, "errors": errors}
