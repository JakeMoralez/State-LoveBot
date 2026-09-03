"""Снятие доступов / сфер после /poolkick."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from database.models.user import AccessLevel
from database.repository.user_repo import UserRepository
from database.spheres import format_spheres_display
from middlewares.access import AccessChecker
from services.panel_client import (
    panel_api_configured,
    remove_sphere_on_poolkick_via_panel,
    revoke_staff_via_panel,
)
from services.panel_db import read_staff_spheres
from services.poolkick_access_keyboard import create_poolkick_access_keyboard
from services.poolkick_sphere_keyboard import create_poolkick_sphere_keyboard
from services.poolkick_sphere_pending import create as create_pending_sphere
from services.self_access import revoke_accesses
from services.staff_nickname_sync import sync_staff_nickname_tag

logger = logging.getLogger(__name__)


@dataclass
class TargetAccessInfo:
    level: int
    spheres: list[str]
    is_senior: bool
    is_judge: bool
    is_attorney: bool
    is_leader: bool
    is_congress_speaker: bool
    is_congress_vice: bool
    has_ca_access: bool

    @property
    def has_staff(self) -> bool:
        return self.level >= AccessLevel.PGS or bool(self.spheres) or self.is_senior

    @property
    def has_roles(self) -> bool:
        return any(
            (
                self.is_judge,
                self.is_attorney,
                self.is_leader,
                self.is_congress_speaker,
                self.is_congress_vice,
                self.has_ca_access,
            )
        )

    @property
    def has_any(self) -> bool:
        return self.has_staff or self.has_roles

    def labels(self) -> list[str]:
        labels: list[str] = []
        if self.level >= AccessLevel.PGS:
            labels.append(AccessChecker.level_name(self.level))
        if self.spheres:
            labels.append(f"сферы: {format_spheres_display(self.spheres)}")
        if self.is_senior:
            labels.append("старший следящий")
        if self.is_judge:
            labels.append("судья")
        if self.is_attorney:
            labels.append("адвокат")
        if self.is_leader:
            labels.append("лидер")
        if self.is_congress_speaker:
            labels.append("спикер конгресса")
        if self.is_congress_vice:
            labels.append("вице-спикер конгресса")
        if self.has_ca_access:
            labels.append("доступ ЦА")
        return labels


async def collect_target_accesses(
    target_vk_id: int,
    server_id: int,
) -> TargetAccessInfo:
    level = await UserRepository.get_access_level(target_vk_id, server_id)
    spheres = list(await read_staff_spheres(target_vk_id, server_id))
    is_senior, _ = await UserRepository.get_senior_status(target_vk_id, server_id)
    access = await UserRepository.get_server_access(target_vk_id, server_id)
    return TargetAccessInfo(
        level=level or 0,
        spheres=spheres,
        is_senior=bool(is_senior),
        is_judge=bool(access and access.is_judge),
        is_attorney=bool(access and access.is_attorney),
        is_leader=bool(access and access.is_leader),
        is_congress_speaker=bool(access and access.is_congress_speaker),
        is_congress_vice=bool(access and access.is_congress_vice),
        has_ca_access=bool(access and access.has_ca_access),
    )


async def _apply_remove_sphere(
    *,
    actor_vk_id: int,
    actor_level: int,
    server_id: int,
    target_vk_id: int,
    sphere: str,
) -> tuple[bool, str]:
    if not panel_api_configured():
        return False, "Панель не настроена."

    ok, result = await remove_sphere_on_poolkick_via_panel(
        actor_vk_id=actor_vk_id,
        server_id=server_id,
        vk_id=target_vk_id,
        sphere=sphere,
    )
    if not ok:
        return False, str(result)

    if isinstance(result, dict) and result.get("full_revoke"):
        await UserRepository.set_access_level(
            target_vk_id, server_id, 0, granted_by=actor_vk_id
        )
        access = await UserRepository.get_server_access(target_vk_id, server_id)
        if access:
            access.is_senior = False
            access.senior_spheres = []
            access.has_ca_access = False
            access.ca_auto_peer_id = None
            await access.save()
        return True, "Доступ следящего снят полностью."

    target_level = await UserRepository.get_access_level(target_vk_id, server_id)
    try:
        await sync_staff_nickname_tag(target_vk_id, server_id, target_level)
    except Exception:
        logger.debug("nick sync after sphere remove failed", exc_info=True)

    return True, f"Снята сфера {format_spheres_display([sphere])}."


async def _apply_full_staff_revoke(
    *,
    actor_vk_id: int,
    actor_level: int,
    server_id: int,
    target_vk_id: int,
) -> tuple[bool, str]:
    if not panel_api_configured():
        return False, "Панель не настроена."

    ok, result = await revoke_staff_via_panel(
        actor_vk_id=actor_vk_id,
        server_id=server_id,
        vk_id=target_vk_id,
    )
    if not ok:
        return False, str(result)

    await UserRepository.set_access_level(target_vk_id, server_id, 0, granted_by=actor_vk_id)
    access = await UserRepository.get_server_access(target_vk_id, server_id)
    if access:
        access.is_senior = False
        access.senior_spheres = []
        access.has_ca_access = False
        access.ca_auto_peer_id = None
        await access.save()

    return True, "Доступ следящего снят полностью."


async def apply_poolkick_sphere_choice(
    *,
    actor_vk_id: int,
    actor_level: int,
    server_id: int,
    target_vk_id: int,
    choice: str,
) -> tuple[bool, str]:
    if choice == "skip":
        return True, "Сферы не изменены."

    if choice == "full":
        return await _apply_full_staff_revoke(
            actor_vk_id=actor_vk_id,
            actor_level=actor_level,
            server_id=server_id,
            target_vk_id=target_vk_id,
        )

    return await _apply_remove_sphere(
        actor_vk_id=actor_vk_id,
        actor_level=actor_level,
        server_id=server_id,
        target_vk_id=target_vk_id,
        sphere=choice,
    )


async def revoke_roles_for_target(vk_id: int, server_id: int) -> list[str]:
    """Снять роли (судья/адвокат/лидер/конгресс/ЦА)."""
    return await revoke_accesses(vk_id, server_id)


async def apply_poolkick_access_choice(
    *,
    actor_vk_id: int,
    actor_level: int,
    server_id: int,
    target_vk_id: int,
    choice: str,
    peer_id: int,
    message,
) -> tuple[bool, str]:
    if choice == "skip":
        return True, "Доступы не изменены."

    if choice == "roles":
        removed = await revoke_roles_for_target(target_vk_id, server_id)
        if not removed:
            return True, "Ролей для снятия не найдено."
        return True, "Сняты роли: " + ", ".join(removed)

    if choice == "all":
        parts: list[str] = []
        removed = await revoke_roles_for_target(target_vk_id, server_id)
        if removed:
            parts.append("роли: " + ", ".join(removed))
        info = await collect_target_accesses(target_vk_id, server_id)
        if info.has_staff:
            ok, detail = await _apply_full_staff_revoke(
                actor_vk_id=actor_vk_id,
                actor_level=actor_level,
                server_id=server_id,
                target_vk_id=target_vk_id,
            )
            if ok:
                parts.append(detail)
            else:
                parts.append(f"staff: {detail}")
                return False, "; ".join(parts) if parts else detail
        return True, "; ".join(parts) if parts else "Нечего снимать."

    if choice == "spheres":
        info = await collect_target_accesses(target_vk_id, server_id)
        if not info.spheres and not info.has_staff:
            return True, "Сфер нет."
        spheres = info.spheres or []
        if not spheres:
            ok, detail = await _apply_full_staff_revoke(
                actor_vk_id=actor_vk_id,
                actor_level=actor_level,
                server_id=server_id,
                target_vk_id=target_vk_id,
            )
            return ok, detail
        token = create_pending_sphere(
            actor_id=actor_vk_id,
            server_id=server_id,
            target_vk_id=target_vk_id,
            peer_id=peer_id,
            target_spheres=spheres,
            chat_sphere=None,
        )
        await message.answer(
            f"📋 Сферы: {format_spheres_display(spheres)}\n"
            "Снять сферу или доступ полностью?",
            keyboard=create_poolkick_sphere_keyboard(token, spheres),
            disable_mentions=1,
        )
        return True, "Выбор сферы."

    return False, "Неизвестный выбор."


async def prompt_poolkick_access_after_kick(
    *,
    api,
    message,
    actor_vk_id: int,
    server_id: int,
    target_vk_id: int,
    flow_token: str,
) -> bool:
    """Показать вопрос по доступам. False = доступов нет."""
    info = await collect_target_accesses(target_vk_id, server_id)
    if not info.has_any:
        return False

    from services.display_name import DisplayNameService

    names = DisplayNameService(api, server_id)
    target_link = await names.link_user(target_vk_id, server_id)
    labels = ", ".join(info.labels())
    await message.answer(
        f"📋 {target_link} — доступы: {labels}.\n"
        "Что сделать?",
        keyboard=create_poolkick_access_keyboard(
            flow_token,
            has_staff=info.has_staff,
            has_roles=info.has_roles,
        ),
        disable_mentions=1,
    )
    return True
