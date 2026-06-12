"""Inline-клавиатуры для модерации форм."""

from __future__ import annotations

from vkbottle import Callback, Keyboard, KeyboardButtonColor

from database.models.court_form import CourtForm


def _base(form_id: int, server_id: int) -> dict:
    return {"form_id": form_id, "server_id": server_id}


def form_review_keyboard(form: CourtForm) -> str:
    base = _base(form.id, form.server_id)
    kb = Keyboard(inline=True)
    kb.add(
        Callback("✅ Принять", payload={"cmd": "form_accept", **base}),
        color=KeyboardButtonColor.POSITIVE,
    )
    kb.add(
        Callback("❌ Отклонить", payload={"cmd": "form_reject", **base}),
        color=KeyboardButtonColor.NEGATIVE,
    )
    return kb.get_json()


def form_batch_keyboard(*, server_id: int, form_ids: list[int]) -> str:
    kb = Keyboard(inline=True)
    kb.add(
        Callback(
            "✅ Принять все",
            payload={
                "cmd": "form_accept_all",
                "server_id": server_id,
                "form_ids": form_ids[:20],
            },
        ),
        color=KeyboardButtonColor.POSITIVE,
    )
    kb.add(
        Callback(
            "❌ Отклонить все",
            payload={
                "cmd": "form_reject_all",
                "server_id": server_id,
                "form_ids": form_ids[:20],
            },
        ),
        color=KeyboardButtonColor.NEGATIVE,
    )
    return kb.get_json()
