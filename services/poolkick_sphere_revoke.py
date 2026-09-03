"""Снятие доступов / сфер после /poolkick."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from database.models.user import AccessLevel
from database.repository.user_repo import UserRepository
from database.spheres import GOV_STRUCTURES, format_spheres_display
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
from services.self_access import revoke_poolkick_roles
from services.staff_hierarchy import can_act_on_target
from services.staff_nickname_sync import sync_staff_nickname_tag
from services.staff_spheres import effective_grantable_sphere_keys

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
    def has_poolkick_roles(self) -> bool:
        return any(
            (
                self.is_judge,
                self.is_attorney,
                self.is_congress_speaker,
                self.is_congress_vice,
                self.has_ca_access,
            )
        )

    @property
    def has_protected_roles(self) -> bool:
        return self.is_leader

    @property
    def has_poolkick_any(self) -> bool:
        return self.has_staff or self.has_poolkick_roles

    @property
    def has_any(self) -> bool:
        return self.has_poolkick_any or self.has_protected_roles

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


async def actor_removable_spheres(actor_vk_id: int, server_id: int) -> set[str]:
    if await UserRepository.is_developer(actor_vk_id):
        from database.spheres import ALL_SPHERE_KEYS

        return set(ALL_SPHERE_KEYS)

    level = await UserRepository.get_access_level(actor_vk_id, server_id)
    actor_spheres = list(await read_staff_spheres(actor_vk_id, server_id))
    if level >= AccessLevel.ZGS:
        return effective_grantable_sphere_keys(level, actor_spheres)

    is_senior, senior_spheres = await UserRepository.get_senior_status(
        actor_vk_id, server_id
    )
    if is_senior and senior_spheres:
        return set(senior_spheres)
    return set()


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
    allowed, hier_err = await can_act_on_target(
        actor_vk_id,
        actor_level,
        target_vk_id,
        server_id,
        on_equal_or_higher="❌ Нельзя снять доступ пользователя своего уровня или выше.",
        skip_if_target_no_access=False,
    )
    if not allowed:
        return False, hier_err or "❌ Недостаточно прав."

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
    combo_sphere: str | None = None,
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

    if choice == "sphere_gos":
        if not combo_sphere:
            return False, "Не указана сфера."
        info = await collect_target_accesses(target_vk_id, server_id)
        to_remove: list[str] = []
        if combo_sphere in info.spheres:
            to_remove.append(combo_sphere)
        if GOV_STRUCTURES in info.spheres and GOV_STRUCTURES not in to_remove:
            to_remove.append(GOV_STRUCTURES)
        if not to_remove:
            return False, "У пользователя нет сфер для снятия."
        parts: list[str] = []
        for sphere in to_remove:
            ok, detail = await _apply_remove_sphere(
                actor_vk_id=actor_vk_id,
                actor_level=actor_level,
                server_id=server_id,
                target_vk_id=target_vk_id,
                sphere=sphere,
            )
            if not ok:
                return False, detail
            parts.append(detail)
        return True, "; ".join(parts)

    return await _apply_remove_sphere(
        actor_vk_id=actor_vk_id,
        actor_level=actor_level,
        server_id=server_id,
        target_vk_id=target_vk_id,
        sphere=choice,
    )


async def apply_poolkick_access_choice(
    *,
    actor_vk_id: int,
    actor_level: int,
    server_id: int,
    target_vk_id: int,
    choice: str,
    peer_id: int,
    message,
    source_sphere: str | None = None,
) -> tuple[bool, str]:
    if choice == "skip":
        return True, "Доступы не изменены."

    if choice == "roles":
        removed = await revoke_poolkick_roles(target_vk_id, server_id)
        if not removed:
            return True, "Ролей для снятия не найдено."
        return True, "Сняты роли: " + ", ".join(removed)

    if choice == "all":
        parts: list[str] = []
        removed = await revoke_poolkick_roles(target_vk_id, server_id)
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

        removable = await actor_removable_spheres(actor_vk_id, server_id)
        can_full, _ = await can_act_on_target(
            actor_vk_id,
            actor_level,
            target_vk_id,
            server_id,
            on_equal_or_higher="",
            skip_if_target_no_access=False,
        )
        if not (spheres and removable & set(spheres)) and not can_full:
            return False, "❌ Недостаточно прав для снятия сфер."

        token = create_pending_sphere(
            actor_id=actor_vk_id,
            server_id=server_id,
            target_vk_id=target_vk_id,
            peer_id=peer_id,
            target_spheres=spheres,
            chat_sphere=source_sphere,
        )
        await message.answer(
            f"📋 Сферы: {format_spheres_display(spheres)}\n"
            "Снять сферу или доступ полностью?",
            keyboard=create_poolkick_sphere_keyboard(
                token,
                owner_id=actor_vk_id,
                target_spheres=spheres,
                source_sphere=source_sphere,
                actor_removable=removable,
                can_full_revoke=can_full,
            ),
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
    if not info.has_poolkick_any:
        return False

    from services.display_name import DisplayNameService

    names = DisplayNameService(api, server_id)
    target_link = await names.link_user(target_vk_id, server_id)
    labels = ", ".join(info.labels())
    lines = [f"📋 {target_link} — доступы: {labels}."]
    if info.has_protected_roles:
        lines.append(
            "ℹ️ Роль лидера не снимается через poolkick — используйте /removeleader."
        )
    lines.append("Что сделать?")
    await message.answer(
        "\n".join(lines),
        keyboard=create_poolkick_access_keyboard(
            flow_token,
            owner_id=actor_vk_id,
            has_staff=info.has_staff,
            has_poolkick_roles=info.has_poolkick_roles,
        ),
        disable_mentions=1,
    )
    return True
