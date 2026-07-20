"""Случайные реакции VK на сообщения в беседах.

Алгоритм:
1) С шансом REACTION_CHANCE% решаем, ставить ли реакцию вообще.
2) Если да — выбираем emoji по весам (сумма = 100).

Базовый набор VK Messenger (messages.sendReaction), id 1–8.
9–10 и прочие «пустые» id не используем.
"""

from __future__ import annotations

import logging
import random
from typing import Any, NamedTuple

from vkbottle import API

logger = logging.getLogger(__name__)

# Общий шанс, что на сообщение вообще будет реакция
DEFAULT_REACTION_CHANCE = 5


class Reaction(NamedTuple):
    reaction_id: int
    emoji: str
    weight: int  # доля среди выбранных реакций, %


# Веса в сумме должны быть 100
REACTIONS: tuple[Reaction, ...] = (
    Reaction(1, "❤️", 22),  # поддержка / согласие
    Reaction(2, "🔥", 20),  # огонь / круто
    Reaction(3, "😂", 18),  # смешно
    Reaction(6, "👍", 18),  # ок / плюс
    Reaction(4, "😮", 10),  # удивление
    Reaction(5, "😢", 9),   # грустно / эмпатия
    Reaction(7, "👎", 2),   # редко: дизлайк
    Reaction(8, "💩", 1),   # очень редко: мем
)

_WEIGHTS = tuple(r.weight for r in REACTIONS)
assert sum(_WEIGHTS) == 100, f"reaction weights must sum to 100, got {sum(_WEIGHTS)}"


def pick_reaction_id() -> int:
    """Взвешенный выбор reaction_id."""
    chosen = random.choices(REACTIONS, weights=_WEIGHTS, k=1)[0]
    return chosen.reaction_id


async def maybe_add_reaction(
    api: API,
    event: dict[str, Any],
    *,
    reaction_chance: int = DEFAULT_REACTION_CHANCE,
) -> None:
    """С шансом reaction_chance% ставит взвешенную реакцию на сообщение в беседе."""
    if random.randint(1, 100) > reaction_chance:
        return

    message = (event.get("object") or {}).get("message") or {}
    if message.get("action"):
        return

    peer_id = message.get("peer_id")
    cmid = message.get("conversation_message_id")
    if not peer_id or int(peer_id) < 2_000_000_000 or not cmid:
        return

    from_id = message.get("from_id") or 0
    if int(from_id) <= 0:
        return

    reaction_id = pick_reaction_id()
    try:
        await api.messages.send_reaction(
            peer_id=int(peer_id),
            cmid=int(cmid),
            reaction_id=reaction_id,
        )
    except Exception as exc:
        logger.debug(
            "reaction failed peer=%s cmid=%s reaction=%s: %s",
            peer_id,
            cmid,
            reaction_id,
            exc,
        )
