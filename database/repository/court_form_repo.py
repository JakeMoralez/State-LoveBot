"""Репозиторий игровых форм судей."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from database.models.court_form import CourtForm, CourtFormStatus


@dataclass
class NewCourtForm:
    form_type: str
    target_nickname: str
    lawsuit_id: int | None = None
    stars: int | None = None
    message: str | None = None
    raw_text: str = ""


class CourtFormRepository:
    @staticmethod
    async def create_batch(
        *,
        server_id: int,
        judge_id: int,
        judge_peer_id: int | None,
        forms: list[NewCourtForm],
    ) -> list[CourtForm]:
        batch_id = uuid.uuid4().hex[:12] if len(forms) > 1 else None
        rows: list[CourtForm] = []
        for item in forms:
            row = await CourtForm.create(
                server_id=server_id,
                judge_id=judge_id,
                judge_peer_id=judge_peer_id,
                form_type=item.form_type,
                target_nickname=item.target_nickname,
                lawsuit_id=item.lawsuit_id,
                stars=item.stars,
                message=item.message,
                raw_text=item.raw_text,
                batch_id=batch_id,
                status=CourtFormStatus.PENDING,
            )
            rows.append(row)
        return rows

    @staticmethod
    async def list_pending(server_id: int) -> list[CourtForm]:
        return (
            await CourtForm.filter(
                server_id=server_id,
                status=CourtFormStatus.PENDING,
            )
            .order_by("created_at", "id")
            .all()
        )

    @staticmethod
    async def list_by_judge(server_id: int, judge_id: int) -> list[CourtForm]:
        return (
            await CourtForm.filter(server_id=server_id, judge_id=judge_id)
            .order_by("-created_at", "-id")
            .limit(50)
            .all()
        )

    @staticmethod
    async def get_pending(server_id: int, form_id: int) -> CourtForm | None:
        return await CourtForm.get_or_none(
            id=form_id,
            server_id=server_id,
            status=CourtFormStatus.PENDING,
        )

    @staticmethod
    async def _mark(
        row: CourtForm,
        *,
        status: str,
        processed_by: int,
        reason: str | None = None,
    ) -> CourtForm:
        row.status = status
        row.processed_by = processed_by
        row.processed_at = datetime.now(timezone.utc)
        row.reject_reason = reason if status == CourtFormStatus.REJECTED else None
        await row.save()
        return row

    @staticmethod
    async def accept(
        server_id: int,
        form_id: int,
        processed_by: int,
    ) -> CourtForm | None:
        row = await CourtFormRepository.get_pending(server_id, form_id)
        if not row:
            return None
        return await CourtFormRepository._mark(
            row,
            status=CourtFormStatus.ACCEPTED,
            processed_by=processed_by,
        )

    @staticmethod
    async def reject(
        server_id: int,
        form_id: int,
        processed_by: int,
        reason: str | None = None,
    ) -> CourtForm | None:
        row = await CourtFormRepository.get_pending(server_id, form_id)
        if not row:
            return None
        return await CourtFormRepository._mark(
            row,
            status=CourtFormStatus.REJECTED,
            processed_by=processed_by,
            reason=reason or "Отклонено модератором ЦА",
        )

    @staticmethod
    async def accept_all(
        server_id: int,
        processed_by: int,
        *,
        form_ids: list[int] | None = None,
    ) -> list[CourtForm]:
        qs = CourtForm.filter(server_id=server_id, status=CourtFormStatus.PENDING)
        if form_ids:
            qs = qs.filter(id__in=form_ids)
        rows = await qs.order_by("created_at", "id").all()
        result: list[CourtForm] = []
        for row in rows:
            result.append(
                await CourtFormRepository._mark(
                    row,
                    status=CourtFormStatus.ACCEPTED,
                    processed_by=processed_by,
                )
            )
        return result

    @staticmethod
    async def reject_all(
        server_id: int,
        processed_by: int,
        *,
        reason: str | None = None,
        form_ids: list[int] | None = None,
    ) -> list[CourtForm]:
        qs = CourtForm.filter(server_id=server_id, status=CourtFormStatus.PENDING)
        if form_ids:
            qs = qs.filter(id__in=form_ids)
        rows = await qs.order_by("created_at", "id").all()
        reject_reason = reason or "Массовый отказ"
        result: list[CourtForm] = []
        for row in rows:
            result.append(
                await CourtFormRepository._mark(
                    row,
                    status=CourtFormStatus.REJECTED,
                    processed_by=processed_by,
                    reason=reject_reason,
                )
            )
        return result
