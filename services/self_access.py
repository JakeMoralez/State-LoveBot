"""Снятие с себя ролей и доступов ЦА одной командой."""

from __future__ import annotations

from database.repository.congress_repo import CongressRepository
from database.repository.forum_role_repo import ForumRoleRepository
from database.repository.user_repo import UserRepository


async def revoke_accesses(vk_id: int, server_id: int) -> list[str]:
    """Снять роли и доступы ЦА с пользователя на сервере."""
    removed: list[str] = []

    if await ForumRoleRepository.clear_judge_role(vk_id, server_id):
        removed.append("судья")

    access = await UserRepository.get_server_access(vk_id, server_id)
    if access and access.is_attorney:
        access.is_attorney = False
        await access.save()
        removed.append("адвокат")

    if await ForumRoleRepository.clear_leader_role(vk_id, server_id):
        removed.append("лидер")

    if await CongressRepository.clear_speaker_for(vk_id, server_id):
        removed.append("спикер конгресса")

    if await CongressRepository.clear_vice_for(vk_id, server_id):
        removed.append("вице-спикер конгресса")

    ca_label = await UserRepository.revoke_self_ca_access(vk_id, server_id)
    if ca_label:
        removed.append(ca_label)

    return removed
