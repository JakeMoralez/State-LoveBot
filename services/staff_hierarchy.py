"""Иерархия: нельзя действовать на равных/выше и на разработчиков."""

from __future__ import annotations

from database.repository.user_repo import UserRepository
from middlewares.access import AccessChecker


async def can_act_on_target(
    actor_vk_id: int,
    actor_level: int,
    target_vk_id: int,
    server_id: int,
    *,
    on_equal_or_higher: str,
    on_developer: str = "❌ Нельзя изменить разработчика.",
    skip_if_target_no_access: bool = True,
) -> tuple[bool, str | None]:
    """Проверка иерархии для модерации / ролей.

    Разработчик-актор проходит всегда. Цель без доступа (ур. ≤ 0) —
    обычно разрешена (кик/мут обычных игроков).
    """
    if actor_vk_id <= 0:
        return False, "❌ Недостаточно прав."

    if await UserRepository.is_developer(actor_vk_id):
        return True, None

    if await UserRepository.is_developer(target_vk_id):
        return False, on_developer

    effective_actor = actor_level
    target_level = await UserRepository.get_access_level(target_vk_id, server_id)
    if skip_if_target_no_access and target_level <= 0:
        return True, None

    if target_level >= effective_actor:
        return False, (
            f"{on_equal_or_higher}\n"
            f"Ваш уровень: {AccessChecker.level_name(effective_actor)}, "
            f"у цели: {AccessChecker.level_name(target_level)}."
        )
    return True, None
