"""Снятие с себя ролей и доступов ЦА одной командой."""

from __future__ import annotations

from database.repository.congress_repo import CongressRepository
from database.repository.forum_role_repo import ForumRoleRepository
from database.repository.user_repo import UserRepository


async def revoke_accesses(vk_id: int, server_id: int) -> list[str]:
    """Снять роли и доступы ЦА с пользователя. Пустой список — нечего снимать."""
    removed: list[str] = []

    if await ForumRoleRepository.clear_judge_role(vk_id):
        removed.append("судья")

    if await CongressRepository.clear_speaker_for(vk_id):
        removed.append("спикер конгресса")

    if await CongressRepository.clear_vice_for(vk_id):
        removed.append("вице-спикер конгресса")

    ca_label = await UserRepository.revoke_self_ca_access(vk_id, server_id)
    if ca_label:
        removed.append(ca_label)

    return removed
