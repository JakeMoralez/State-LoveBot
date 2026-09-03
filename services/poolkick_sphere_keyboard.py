"""Клавиатура выбора сферы после /poolkick (контекст беседы, как scope кика)."""

from __future__ import annotations

from vkbottle import Callback, Keyboard, KeyboardButtonColor

from database.spheres import CENTRAL_APPARATUS, GOV_STRUCTURES
from services.staff_nickname import MINISTRY_NICK_TAGS, STRUCTURE_NICK_TAGS


def _short_sphere(sphere: str) -> str:
    return (
        MINISTRY_NICK_TAGS.get(sphere)
        or STRUCTURE_NICK_TAGS.get(sphere)
        or sphere
    )


def _sphere_button_label(sphere: str) -> str:
    if sphere == CENTRAL_APPARATUS:
        return "Снять ЦА"
    if sphere == GOV_STRUCTURES:
        return "Снять гос"
    short = _short_sphere(sphere)
    return f"Снять {short}"


def create_poolkick_sphere_keyboard(
    token: str,
    *,
    owner_id: int,
    target_spheres: list[str],
    source_sphere: str | None,
    actor_removable: set[str],
    can_full_revoke: bool,
) -> str:
    target_set = set(target_spheres)
    removable = target_set & actor_removable
    kb = Keyboard(inline=True)
    first = True
    shown: set[str] = set()

    def _add_button(label: str, choice: str, *, sphere: str | None = None) -> None:
        nonlocal first
        payload: dict = {
            "cmd": "pk_sphere",
            "token": token,
            "choice": choice,
            "owner": owner_id,
        }
        if sphere is not None:
            payload["sphere"] = sphere
        if not first:
            kb.row()
        first = False
        kb.add(
            Callback(label, payload=payload),
            color=KeyboardButtonColor.SECONDARY,
        )

    if (
        source_sphere
        and source_sphere in removable
        and source_sphere not in shown
    ):
        _add_button(
            _sphere_button_label(source_sphere),
            source_sphere,
            sphere=source_sphere,
        )
        shown.add(source_sphere)

    if (
        CENTRAL_APPARATUS in removable
        and CENTRAL_APPARATUS not in shown
    ):
        _add_button("Снять ЦА", CENTRAL_APPARATUS, sphere=CENTRAL_APPARATUS)
        shown.add(CENTRAL_APPARATUS)

    if GOV_STRUCTURES in removable and GOV_STRUCTURES not in shown:
        _add_button("Снять гос", GOV_STRUCTURES, sphere=GOV_STRUCTURES)
        shown.add(GOV_STRUCTURES)

    if (
        source_sphere
        and source_sphere != GOV_STRUCTURES
        and source_sphere in removable
        and GOV_STRUCTURES in removable
    ):
        _add_button("Снять все", "sphere_gos", sphere=source_sphere)

    extras = [
        s
        for s in target_spheres
        if s in removable and s not in shown
    ][:3]
    for sphere in extras:
        _add_button(_sphere_button_label(sphere), sphere, sphere=sphere)
        shown.add(sphere)

    if can_full_revoke:
        if not first:
            kb.row()
        first = False
        kb.add(
            Callback(
                "Снять полностью",
                payload={
                    "cmd": "pk_sphere",
                    "token": token,
                    "choice": "full",
                    "owner": owner_id,
                },
            ),
            color=KeyboardButtonColor.NEGATIVE,
        )

    if not first:
        kb.row()
    kb.add(
        Callback(
            "Не снимать",
            payload={
                "cmd": "pk_sphere",
                "token": token,
                "choice": "skip",
                "owner": owner_id,
            },
        ),
        color=KeyboardButtonColor.PRIMARY,
    )
    return kb.get_json()
