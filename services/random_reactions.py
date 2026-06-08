"""Случайные реакции VK на сообщения в беседах (как legacy/forum_bot)."""

from __future__ import annotations

import logging
import random
from typing import Any

from vkbottle import API

logger = logging.getLogger(__name__)

REACTION_IDS = tuple(range(1, 11))
DEFAULT_REACTION_CHANCE = 5


async def maybe_add_reaction(
    api: API,
    event: dict[str, Any],
    *,
    reaction_chance: int = DEFAULT_REACTION_CHANCE,
) -> None:
    """С шансом reaction_chance% ставит случайную реакцию на сообщение в беседе."""
    if random.randint(1, 100) > reaction_chance:
        return

    message = (event.get("object") or {}).get("message") or {}
    peer_id = message.get("peer_id")
    cmid = message.get("conversation_message_id")
    if not peer_id or int(peer_id) < 2_000_000_000 or not cmid:
        return

    from_id = message.get("from_id") or 0
    if int(from_id) <= 0:
        return

    reaction_id = random.choice(REACTION_IDS)
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
