"""Снятие сферы / доступа следящего после успешного /poolkick."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

from database.models.user import AccessLevel
from database.repository.user_repo import UserRepository
from database.spheres import (
    CENTRAL_APPARATUS,
    DEFENSE,
    GOV_STRUCTURES,
    HEALTH,
    ILLEGAL_STRUCTURES,
    JUSTICE,
    format_spheres_display,
)
from services.panel_client import (
    panel_api_configured,
    remove_sphere_on_poolkick_via_panel,
    revoke_staff_via_panel,
)
from services.panel_db import read_staff_spheres
from services.poolkick_sphere_keyboard import create_poolkick_sphere_keyboard
from services.poolkick_sphere_pending import create as create_pending_sphere
from services.staff_spheres import pool_alias_to_sphere
from services.staff_nickname_sync import sync_staff_nickname_tag

logger = logging.getLogger(__name__)

MINISTRY_SPHERES = frozenset(
    {CENTRAL_APPARATUS, JUSTICE, DEFENSE, HEALTH},
)
STRUCTURE_SPHERES = frozenset({GOV_STRUCTURES, ILLEGAL_STRUCTURES})


@dataclass(frozen=True)
class SphereDecision:
    kind: Literal["auto", "prompt", "skip"]
    sphere: str | None = None


def decide_poolkick_sphere_action(
    chat_sphere: str | None,
    target_spheres: list[str],
) -> SphereDecision:
    if not target_spheres:
        return SphereDecision("skip")

    if chat_sphere in MINISTRY_SPHERES and chat_sphere in target_spheres:
        return SphereDecision("auto", chat_sphere)

    if chat_sphere in STRUCTURE_SPHERES and chat_sphere in target_spheres:
        if target_spheres == [chat_sphere]:
            return SphereDecision("auto", chat_sphere)
        return SphereDecision("prompt")

    return SphereDecision("prompt")


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


async def _apply_full_revoke(
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
        return await _apply_full_revoke(
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


async def handle_poolkick_sphere_after_kick(
    *,
    api,
    message,
    actor_vk_id: int,
    actor_level: int,
    server_id: int,
    target_vk_id: int,
    chat,
    kicked_count: int,
) -> None:
    """После успешного poolkick — авто или запрос снятия сферы."""
    if kicked_count <= 0:
        return

    target_level = await UserRepository.get_access_level(target_vk_id, server_id)
    if target_level < AccessLevel.PGS:
        return

    target_spheres = list(await read_staff_spheres(target_vk_id, server_id))
    if not target_spheres:
        return

    pool = getattr(chat, "pool", None)
    pool_name = getattr(pool, "name", None) if pool else None
    chat_sphere = pool_alias_to_sphere(getattr(chat, "alias", None), pool_name)
    decision = decide_poolkick_sphere_action(chat_sphere, target_spheres)

    from services.display_name import DisplayNameService

    names = DisplayNameService(api, server_id)
    target_link = await names.link_user(target_vk_id, server_id)

    if decision.kind == "skip":
        return

    if decision.kind == "auto" and decision.sphere:
        ok, detail = await _apply_remove_sphere(
            actor_vk_id=actor_vk_id,
            actor_level=actor_level,
            server_id=server_id,
            target_vk_id=target_vk_id,
            sphere=decision.sphere,
        )
        if ok:
            await message.answer(
                f"📋 {target_link} — {detail}",
                disable_mentions=1,
            )
        elif detail and "Нет прав" in detail:
            await message.answer(f"⚠️ {detail}", disable_mentions=1)
        return

    token = create_pending_sphere(
        actor_id=actor_vk_id,
        server_id=server_id,
        target_vk_id=target_vk_id,
        peer_id=message.peer_id,
        target_spheres=target_spheres,
        chat_sphere=chat_sphere,
    )
    chat_hint = (
        format_spheres_display([chat_sphere])
        if chat_sphere
        else "не определена"
    )
    await message.answer(
        f"📋 {target_link} исключён из пула.\n"
        f"Сферы: {format_spheres_display(target_spheres)}\n"
        f"Сфера беседы: {chat_hint}\n\n"
        "Снять сферу или доступ полностью?",
        keyboard=create_poolkick_sphere_keyboard(token, target_spheres),
        disable_mentions=1,
    )
