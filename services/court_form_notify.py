"""Уведомления о формах: беседа след. ЦА и беседа судей."""

from __future__ import annotations

import logging
from datetime import datetime

from vkbottle import API

from database.models.court_form import CourtForm, CourtFormStatus
from database.models.role_chat import ForumRoleKey
from database.repository.forum_role_repo import ForumRoleRepository
from services.court_form_keyboard import form_batch_keyboard, form_review_keyboard
from services.court_forms import VK_MESSAGE_LIMIT, format_forms_copy_list, form_type_label
from services.display_name import DisplayNameService

logger = logging.getLogger(__name__)


class CourtFormNotifier:
    def __init__(self, api: API) -> None:
        self._api = api
        self._names = DisplayNameService(api)

    async def _send(self, peer_id: int | None, text: str, *, keyboard: str | None = None) -> None:
        if not peer_id:
            return
        params: dict = {
            "peer_id": peer_id,
            "message": text,
            "random_id": 0,
            "disable_mentions": 1,
        }
        if keyboard:
            params["keyboard"] = keyboard
        try:
            await self._api.messages.send(**params)
        except Exception as exc:
            logger.warning("court form notify peer=%s: %s", peer_id, exc)

    async def notify_new_forms(
        self,
        *,
        server_id: int,
        judge_id: int,
        forms: list[CourtForm],
    ) -> None:
        if not forms:
            return

        sled_peer = await ForumRoleRepository.get_role_chat(
            ForumRoleKey.SLED_CA,
            server_id,
        )
        if not sled_peer:
            logger.info("sled_ca chat not configured server=%s", server_id)
            return

        judge = await self._names.link_user(judge_id, server_id)
        header = (
            "📥 Новые формы на рассмотрение\n\n"
            f"👨‍⚖️ Судья: {judge}\n"
            f"📄 Количество: {len(forms)}\n"
        )
        body_chunks = format_forms_copy_list(forms, with_ids=False, empty_text=None)
        keyboard = (
            form_batch_keyboard(
                server_id=server_id,
                form_ids=[row.id for row in forms],
            )
            if len(forms) > 1
            else form_review_keyboard(forms[0])
        )

        if not body_chunks:
            await self._send(sled_peer, header, keyboard=keyboard)
            return

        first_body = body_chunks[0]
        combined = f"{header}\n\n{first_body}"
        if len(combined) <= VK_MESSAGE_LIMIT:
            await self._send(sled_peer, combined, keyboard=keyboard)
            for chunk in body_chunks[1:]:
                await self._send(sled_peer, chunk)
        else:
            await self._send(sled_peer, header, keyboard=keyboard)
            for chunk in body_chunks:
                await self._send(sled_peer, chunk)

    async def notify_decision(
        self,
        *,
        server_id: int,
        form: CourtForm,
        reviewer_id: int,
        accepted: bool,
        reason: str | None = None,
    ) -> None:
        court_peer = await ForumRoleRepository.get_role_chat(
            ForumRoleKey.JUDGE,
            server_id,
        )
        reviewer = await self._names.link_user(reviewer_id, server_id)
        status = "✅ ПРИНЯТА" if accepted else "❌ ОТКЛОНЕНА"
        when = datetime.now().strftime("%d.%m.%Y %H:%M")

        lines = [
            f"📬 Решение по форме #{form.id}",
            "",
            f"Статус: {status}",
            f"Тип: {form_type_label(form.form_type)}",
            f"Игрок: {form.target_nickname}",
            f"Модератор: {reviewer}",
            f"Время: {when}",
        ]
        if not accepted and reason:
            lines.extend(["", f"Причина: {reason}"])
        lines.extend(["", "━━━━━━━━━━━━━━", form.raw_text.strip()])

        await self._send(court_peer, "\n".join(lines))

        if form.judge_peer_id:
            short = (
                f"✅ Форма #{form.id} ({form.target_nickname}) принята."
                if accepted
                else f"❌ Форма #{form.id} ({form.target_nickname}) отклонена."
            )
            if not accepted and reason:
                short += f"\nПричина: {reason}"
            await self._send(form.judge_peer_id, short)

    async def notify_bulk_decision(
        self,
        *,
        server_id: int,
        forms: list[CourtForm],
        reviewer_id: int,
        accepted: bool,
        reason: str | None = None,
    ) -> None:
        for row in forms:
            await self.notify_decision(
                server_id=server_id,
                form=row,
                reviewer_id=reviewer_id,
                accepted=accepted,
                reason=reason,
            )
