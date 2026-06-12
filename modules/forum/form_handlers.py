"""Команды форм: /form, /forms, /myform, accept/reject."""

from __future__ import annotations

import json
import logging

from vkbottle import API, GroupEventType
from vkbottle.bot import Bot, Message, MessageEvent
from vkbottle.dispatch.rules.base import FuncRule

from database.repository.court_form_repo import CourtFormRepository
from database.repository.user_repo import UserRepository
from middlewares.action_logger import ActionLogger
from middlewares.ca_access import requires_ca_scope
from middlewares.forum_access import requires_judge_or_developer
from services.command_utils import matches_cmd, strip_cmd
from services.court_form_notify import CourtFormNotifier
from services.court_forms import (
    FORM_HELP_TEXT,
    format_my_forms,
    format_pending_copy_list,
    format_pending_list_with_ids,
    format_review_usage,
    format_submit_result,
    parse_form_batch,
)

logger = logging.getLogger(__name__)

_FORM_CALLBACK_CMDS = frozenset({
    "form_accept",
    "form_reject",
    "form_accept_all",
    "form_reject_all",
})


async def _can_review_forms(user_id: int, server_id: int) -> bool:
    if await UserRepository.is_developer(user_id):
        return True
    return await UserRepository.can_use_ca_scope(user_id, server_id)


def _parse_target_arg(raw: str) -> tuple[str, str | None]:
    text = (raw or "").strip()
    if not text:
        return "", None
    lower = text.lower()
    if lower in ("all", "все", "*"):
        return "all", None
    parts = text.split(maxsplit=1)
    if parts[0].isdigit():
        return parts[0], (parts[1].strip() if len(parts) > 1 else None)
    return "", text


def register_form_handlers(
    bot: Bot,
    api: API,
    action_logger: ActionLogger,
) -> None:
    notifier = CourtFormNotifier(api)

    async def _notify_decisions(
        server_id: int,
        rows: list,
        reviewer_id: int,
        *,
        accepted: bool,
        reason: str | None = None,
    ) -> None:
        if not rows:
            return
        await notifier.notify_bulk_decision(
            server_id=server_id,
            forms=rows,
            reviewer_id=reviewer_id,
            accepted=accepted,
            reason=reason,
        )

    @bot.on.message(FuncRule(lambda m: matches_cmd(m.text or "", "form")))
    @requires_judge_or_developer
    async def submit_forms(message: Message, server_id: int = 0) -> None:
        body = strip_cmd(message.text or "", "form")
        if not body:
            await message.answer(FORM_HELP_TEXT)
            return

        parsed, errors = parse_form_batch(body)
        if not parsed and not errors:
            await message.answer("❌ Не найдено команд форм.\n\n" + FORM_HELP_TEXT)
            return

        saved_rows = []
        if parsed:
            saved_rows = await CourtFormRepository.create_batch(
                server_id=server_id,
                judge_id=message.from_id or 0,
                judge_peer_id=message.peer_id,
                forms=parsed,
            )
            await notifier.notify_new_forms(
                server_id=server_id,
                judge_id=message.from_id or 0,
                forms=saved_rows,
            )

        await message.answer(
            format_submit_result(len(parsed), len(errors), errors=errors or None)
        )
        await action_logger.log_user(
            "court_form_submit",
            message.from_id,
            f"ok={len(parsed)}, err={len(errors)}",
            "Записано" if parsed else "Ошибка",
            source_peer_id=message.peer_id,
        )

    @bot.on.message(FuncRule(lambda m: matches_cmd(m.text or "", "myform")))
    @requires_judge_or_developer
    async def my_forms(message: Message, server_id: int = 0) -> None:
        rows = await CourtFormRepository.list_by_judge(
            server_id,
            message.from_id or 0,
        )
        await message.answer(format_my_forms(rows))

    @bot.on.message(
        FuncRule(
            lambda m: matches_cmd(m.text or "", "forms")
            or matches_cmd(m.text or "", "formsid")
        )
    )
    @requires_ca_scope
    async def list_forms(message: Message, server_id: int = 0) -> None:
        text = message.text or ""
        with_ids = matches_cmd(text, "formsid")
        if not with_ids:
            arg = strip_cmd(text, "forms").lower()
            with_ids = arg in ("id", "ids")

        rows = await CourtFormRepository.list_pending(server_id)
        chunks = (
            format_pending_list_with_ids(rows)
            if with_ids
            else format_pending_copy_list(rows)
        )
        for chunk in chunks:
            await message.answer(chunk)

    @bot.on.message(FuncRule(lambda m: matches_cmd(m.text or "", "acceptform")))
    @requires_ca_scope
    async def accept_form(message: Message, server_id: int = 0) -> None:
        raw = strip_cmd(message.text or "", "acceptform")
        target, _ = _parse_target_arg(raw)
        if not target:
            await message.answer(format_review_usage())
            return

        if target == "all":
            rows = await CourtFormRepository.accept_all(
                server_id,
                message.from_id or 0,
            )
            if not rows:
                await message.answer("📭 Нет форм в очереди.")
                return
            await _notify_decisions(
                server_id,
                rows,
                message.from_id or 0,
                accepted=True,
            )
            await message.answer(f"✅ Принято форм: {len(rows)}")
            await action_logger.log_user(
                "court_form_accept",
                message.from_id,
                f"all, count={len(rows)}",
                "Принято",
                source_peer_id=message.peer_id,
            )
            return

        row = await CourtFormRepository.accept(
            server_id,
            int(target),
            message.from_id or 0,
        )
        if not row:
            await message.answer(f"❌ Форма #{target} не найдена или уже обработана.")
            return
        await notifier.notify_decision(
            server_id=server_id,
            form=row,
            reviewer_id=message.from_id or 0,
            accepted=True,
        )
        await message.answer(f"✅ Форма #{row.id} принята.")
        await action_logger.log_user(
            "court_form_accept",
            message.from_id,
            f"#{row.id}",
            "Принята",
            source_peer_id=message.peer_id,
        )

    @bot.on.message(FuncRule(lambda m: matches_cmd(m.text or "", "rejectform")))
    @requires_ca_scope
    async def reject_form(message: Message, server_id: int = 0) -> None:
        raw = strip_cmd(message.text or "", "rejectform")
        target, reason = _parse_target_arg(raw)
        if not target:
            await message.answer(format_review_usage())
            return

        if target == "all":
            rows = await CourtFormRepository.reject_all(
                server_id,
                message.from_id or 0,
                reason=reason,
            )
            if not rows:
                await message.answer("📭 Нет форм в очереди.")
                return
            await _notify_decisions(
                server_id,
                rows,
                message.from_id or 0,
                accepted=False,
                reason=reason,
            )
            await message.answer(f"❌ Отклонено форм: {len(rows)}")
            await action_logger.log_user(
                "court_form_reject",
                message.from_id,
                f"all, count={len(rows)}",
                "Отклонено",
                source_peer_id=message.peer_id,
            )
            return

        row = await CourtFormRepository.reject(
            server_id,
            int(target),
            message.from_id or 0,
            reason=reason,
        )
        if not row:
            await message.answer(f"❌ Форма #{target} не найдена или уже обработана.")
            return
        await notifier.notify_decision(
            server_id=server_id,
            form=row,
            reviewer_id=message.from_id or 0,
            accepted=False,
            reason=reason,
        )
        await message.answer(f"❌ Форма #{row.id} отклонена.")
        await action_logger.log_user(
            "court_form_reject",
            message.from_id,
            f"#{row.id}",
            "Отклонена",
            source_peer_id=message.peer_id,
        )

    @bot.on.raw_event(GroupEventType.MESSAGE_EVENT, MessageEvent, blocking=False)
    async def form_callback(event: MessageEvent) -> None:
        payload = event.payload
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                return
        if not isinstance(payload, dict):
            return

        cmd = payload.get("cmd")
        if cmd not in _FORM_CALLBACK_CMDS:
            return

        server_id = int(payload.get("server_id") or 0)
        if not server_id:
            from middlewares.access import AccessChecker

            server_id = await AccessChecker.resolve_server_id(
                event.peer_id,
                event.user_id,
            )

        if not await _can_review_forms(event.user_id, server_id):
            await event.show_snackbar("⛔ Нужен доступ ЦА.")
            return

        try:
            if cmd == "form_accept":
                form_id = int(payload.get("form_id") or 0)
                row = await CourtFormRepository.accept(
                    server_id,
                    form_id,
                    event.user_id,
                )
                if not row:
                    await event.show_snackbar("❌ Форма не найдена")
                    return
                await notifier.notify_decision(
                    server_id=server_id,
                    form=row,
                    reviewer_id=event.user_id,
                    accepted=True,
                )
                await event.send_message(f"✅ Форма #{row.id} принята.")
                await action_logger.log_user(
                    "court_form_accept",
                    event.user_id,
                    f"#{row.id}",
                    "Принята (кнопка)",
                    source_peer_id=event.peer_id,
                )

            elif cmd == "form_reject":
                form_id = int(payload.get("form_id") or 0)
                row = await CourtFormRepository.reject(
                    server_id,
                    form_id,
                    event.user_id,
                )
                if not row:
                    await event.show_snackbar("❌ Форма не найдена")
                    return
                await notifier.notify_decision(
                    server_id=server_id,
                    form=row,
                    reviewer_id=event.user_id,
                    accepted=False,
                )
                await event.send_message(
                    f"❌ Форма #{row.id} отклонена.\n"
                    f"С указанием причины: /rejectform {row.id} текст"
                )
                await action_logger.log_user(
                    "court_form_reject",
                    event.user_id,
                    f"#{row.id}",
                    "Отклонена (кнопка)",
                    source_peer_id=event.peer_id,
                )

            elif cmd == "form_accept_all":
                form_ids = payload.get("form_ids") or []
                ids = [int(x) for x in form_ids if str(x).isdigit()]
                rows = await CourtFormRepository.accept_all(
                    server_id,
                    event.user_id,
                    form_ids=ids or None,
                )
                if not rows:
                    await event.show_snackbar("📭 Нет форм в очереди")
                    return
                await _notify_decisions(
                    server_id,
                    rows,
                    event.user_id,
                    accepted=True,
                )
                await event.send_message(f"✅ Принято форм: {len(rows)}")
                await action_logger.log_user(
                    "court_form_accept",
                    event.user_id,
                    f"all btn, count={len(rows)}",
                    "Принято",
                    source_peer_id=event.peer_id,
                )

            elif cmd == "form_reject_all":
                form_ids = payload.get("form_ids") or []
                ids = [int(x) for x in form_ids if str(x).isdigit()]
                rows = await CourtFormRepository.reject_all(
                    server_id,
                    event.user_id,
                    form_ids=ids or None,
                )
                if not rows:
                    await event.show_snackbar("📭 Нет форм в очереди")
                    return
                await _notify_decisions(
                    server_id,
                    rows,
                    event.user_id,
                    accepted=False,
                )
                await event.send_message(f"❌ Отклонено форм: {len(rows)}")
                await action_logger.log_user(
                    "court_form_reject",
                    event.user_id,
                    f"all btn, count={len(rows)}",
                    "Отклонено",
                    source_peer_id=event.peer_id,
                )

            await event.send_empty_answer()
        except Exception as exc:
            logger.exception("form callback %s: %s", cmd, exc)
            await event.show_snackbar("❌ Ошибка обработки формы")
