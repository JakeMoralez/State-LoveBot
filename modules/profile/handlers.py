"""Профили: /setnick, /who, /setlevel."""

from __future__ import annotations

import logging
import random
import re

from vkbottle import API
from vkbottle.bot import Bot, Message
from vkbottle.dispatch.rules.base import FuncRule

from database.models.user import AccessLevel
from database.repository.user_repo import UserRepository
from middlewares.access import AccessChecker, requires_level, requires_public
from middlewares.congress_access import requires_setnick
from middlewares.action_logger import ActionLogger
from services.command_utils import (
    dual,
    dual_args,
    dual_with_args,
    is_user_info_cmd,
    matches_cmd,
    matches_who,
    strip_cmd,
)
from services.display_name import DisplayNameService
from services.nickname import NicknameValidator
from services.panel_client import set_staff_spheres_via_panel
from services.profile_card import format_user_profile_card
from services.staff_display import format_staff_list
from services.staff_spheres import (
    format_spheres_display,
    parse_sphere_tokens,
    validate_spheres,
)
from services.vk_resolver import VKResolver

logger = logging.getLogger(__name__)

_WHO_EMOJIS = (
    "😀", "😃", "😄", "😁", "😆", "😅", "🤣", "😂", "🙂", "🙃", "😉", "😊",
    "😇", "🥰", "😍", "🤩", "😘", "😗", "😚", "😙", "🥲", "😋", "😛", "😜",
    "🤪", "😝", "🤑", "🤗", "🤭", "🤫", "🤔", "🤐", "🤨", "😐", "😑", "😶",
    "😏", "😒", "🙄", "😬", "🤥", "😌", "😔", "😪", "🤤", "😴", "😷", "🤒",
    "🤕", "🤢", "🤮", "🤧", "🥵", "🥶", "🥴", "😵", "🤯", "🤠", "🥳", "🥸",
    "😎", "🤓", "🧐", "😕", "😟", "🙁", "☹️", "😮", "😯", "😲", "😳", "🥺",
    "😦", "😧", "😨", "😰", "😥", "😢", "😭", "😱", "😖", "😣", "😞", "😓",
    "😩", "😫", "🥱", "😤", "😡", "😠", "🤬", "😈", "👿", "🫠", "🫡", "🫢",
    "🫣", "🫤", "🫥", "🫨",
)


_VK_REF = r"(?:https?://)?(?:m\.)?(?:vk\.com|vk\.ru)/(?:id\d+|[\w.]+)"
_SETNICK_LEAD = re.compile(
    rf"^(?:\[id(\d+)\|[^\]]+\]|@(\S+)|\[[^\]]+\]\((?:https?://)?(?:m\.)?(?:vk\.com|vk\.ru)/(?:id\d+|[\w.]+)\)|({_VK_REF}))(?:\s+)(.+)$",
    re.DOTALL | re.IGNORECASE,
)


_SETNICK_FORMAT_ERR = (
    "❌ Неверный формат.\n"
    "Сначала пинг: @user, [id|имя] или vk.ru/…, затем ник.\n"
    "Или ответом на сообщение."
)

_NICK_TARGET_ERR = (
    "❌ Неверный формат.\n"
    "Укажите @user, [id|имя], vk.ru/… или ответьте на сообщение."
)

_VK_REF_ONLY = re.compile(
    rf"^(?:\[id(\d+)\|[^\]]+\]|@(\S+)|\[[^\]]+\]\((?:https?://)?(?:m\.)?(?:vk\.com|vk\.ru)/(?:id\d+|[\w.]+)\)|({_VK_REF}))$",
    re.IGNORECASE,
)

_SETSPHERE_USAGE = (
    "❌ /setsphere [пинг|ответ] сферы [ст сферы]\n"
    "Сферы: ца мю мо мз гос нелег сервер\n"
    "• /setsphere @user ца\n"
    "• /setsphere @user ца мю\n"
    "• /setsphere @user ца ст мю     — старший/совмещение\n"
    "• /setsphere @user ца ст -      — снять старшего\n"
    "• ответом: /setsphere ца ст мю"
)

# Разделитель: ст / старший / след (+старший для совместимости)
_SENIOR_SPLIT_RE = re.compile(
    r"(?:"
    r"\s+(?:ст|старший|сеньор|след|следящий)(?:\s*[:＝=]|\s+)"
    r"|\s+\+(?:старший|сеньор|след(?:ящий)?)\s*"
    r"|\s+(?:--senior|senior)(?::|-)?\s*"
    r"|\s+\|\s*"
    r")",
    re.IGNORECASE,
)


def _split_setsphere_payload(raw: str) -> tuple[str, str | None]:
    """'ца мю ст мз' → ('ца мю', 'мз'); без ст → (весь текст, None)."""
    text = (raw or "").strip()
    if not text:
        return "", None
    match = _SENIOR_SPLIT_RE.search(text)
    if not match:
        return text, None
    return text[: match.start()].strip(), text[match.end() :].strip()


async def _parse_setnick(message: Message, api: API) -> tuple[int | None, str | None, str | None]:
    """(target_id, nickname, error_message)."""
    args = strip_cmd(message.text or "", "setnick")
    if not args:
        return None, None, _SETNICK_FORMAT_ERR

    resolver = VKResolver(api)

    if message.reply_message and message.reply_message.from_id > 0:
        nick = args.strip()
        if not nick:
            return None, None, "❌ Укажите никнейм."
        return message.reply_message.from_id, nick, None

    lead = _SETNICK_LEAD.match(args)
    if not lead:
        return None, None, _SETNICK_FORMAT_ERR

    vk_id_raw, screen, url_ref, nickname = (
        lead.group(1),
        lead.group(2),
        lead.group(3),
        lead.group(4).strip(),
    )
    if not nickname:
        return None, None, "❌ Укажите никнейм."

    if vk_id_raw:
        return int(vk_id_raw), nickname, None

    if screen:
        resolved = await resolver.resolve(f"@{screen}")
        if resolved:
            return resolved.vk_id, nickname, None
        return None, None, _SETNICK_FORMAT_ERR

    if url_ref:
        resolved = await resolver.resolve(url_ref)
        if resolved:
            return resolved.vk_id, nickname, None
        return None, None, _SETNICK_FORMAT_ERR

    return None, None, _SETNICK_FORMAT_ERR


async def _staff_nick_blocked_message(
    target_id: int,
    server_id: int,
    names: DisplayNameService,
) -> str | None:
    """Ник следящего (ур. 1+) — только через сайт, не /snick и не /rnick."""
    if await UserRepository.get_access_level(target_id, server_id) < AccessLevel.PGS:
        return None
    link = await names.link_user(target_id, server_id)
    return (
        f"❌ У {link} есть доступ следящего — "
        "ник меняется через сайт (Команда → профиль)."
    )


async def _parse_nick_target(message: Message, api: API) -> tuple[int | None, str | None]:
    """(target_id, error_message) — для /rnick."""
    args = strip_cmd(message.text or "", "rnick")
    resolver = VKResolver(api)

    if message.reply_message and message.reply_message.from_id > 0:
        return message.reply_message.from_id, None

    if not args:
        return None, _NICK_TARGET_ERR

    lead = _VK_REF_ONLY.match(args.strip())
    if not lead:
        return None, _NICK_TARGET_ERR

    vk_id_raw, screen, url_ref = lead.group(1), lead.group(2), lead.group(3)
    if vk_id_raw:
        return int(vk_id_raw), None
    if screen:
        resolved = await resolver.resolve(f"@{screen}")
        if resolved:
            return resolved.vk_id, None
        return None, _NICK_TARGET_ERR
    if url_ref:
        resolved = await resolver.resolve(url_ref)
        if resolved:
            return resolved.vk_id, None
        return None, _NICK_TARGET_ERR

    return None, _NICK_TARGET_ERR


async def _parse_profile_target(message: Message, api: API, cmd: str) -> tuple[int | None, str | None]:
    """(target_id, error_message) — для /info и похожих."""
    args = strip_cmd(message.text or "", cmd)
    resolver = VKResolver(api)

    if message.reply_message and message.reply_message.from_id > 0:
        if args:
            return None, (
                "❌ Укажите только @user, ссылку VK или ответьте на сообщение, но не оба сразу."
            )
        return message.reply_message.from_id, None

    if not args:
        if message.from_id:
            return message.from_id, None
        return None, "❌ Не удалось определить пользователя."

    lead = _VK_REF_ONLY.match(args.strip())
    if not lead:
        return None, _NICK_TARGET_ERR

    vk_id_raw, screen, url_ref = lead.group(1), lead.group(2), lead.group(3)
    if vk_id_raw:
        return int(vk_id_raw), None
    if screen:
        resolved = await resolver.resolve(f"@{screen}")
        if resolved:
            return resolved.vk_id, None
        return None, _NICK_TARGET_ERR
    if url_ref:
        resolved = await resolver.resolve(url_ref)
        if resolved:
            return resolved.vk_id, None
        return None, _NICK_TARGET_ERR

    return None, _NICK_TARGET_ERR


async def format_who_card(vk_id: int, api: API, server_id: int = 0) -> str:
    emoji = random.choice(_WHO_EMOJIS)
    link = await DisplayNameService(api).link_user(vk_id, server_id)
    return f"{emoji} {link}"


def register_profile(bot: Bot, api: API, action_logger: ActionLogger) -> None:
    names = DisplayNameService(api)

    @bot.on.message(FuncRule(lambda m: matches_cmd(m.text or "", "setnick")))
    @requires_setnick
    async def setnick(
        message: Message,
        server_id: int = 0,
        access_level: int = 0,
    ) -> None:
        target_id, nickname, err = await _parse_setnick(message, api)
        if err:
            await message.answer(err)
            return
        if not nickname or target_id is None:
            await message.answer("❌ Укажите никнейм.")
            return

        blocked = await _staff_nick_blocked_message(target_id, server_id, names)
        if blocked:
            await message.answer(blocked, disable_mentions=1)
            return

        ok, val_err = NicknameValidator.validate(nickname)
        if not ok:
            await message.answer(f"❌ {val_err}")
            return

        if await UserRepository.has_nickname(target_id, server_id):
            await message.answer("❌ Никнейм уже установлен. Сначала /rnick.")
            return

        if await UserRepository.is_nickname_taken(
            server_id,
            nickname,
            exclude_vk_id=target_id,
        ):
            await message.answer("❌ Такой ник уже занят на этом сервере.")
            return

        if target_id != message.from_id:
            resolver = VKResolver(api)
            resolved = await resolver.resolve(str(target_id))
            await UserRepository.ensure_user(
                vk_id=target_id,
                username=resolved.username if resolved else None,
                added_by=message.from_id,
            )

        await UserRepository.set_nickname(target_id, server_id, nickname)
        actor = await names.format_setnick_actor(message.from_id or 0, server_id)
        target_link = DisplayNameService.nick_link(target_id, nickname)
        await message.answer(
            f"{actor} поставил никнейм '{nickname}' {target_link}.",
            disable_mentions=1,
        )
        await action_logger.log_user(
            "setnick",
            message.from_id,
            f"id{target_id} → {nickname}",
            "Установлен",
            source_peer_id=message.peer_id,
        )

    @bot.on.message(FuncRule(lambda m: matches_cmd(m.text or "", "rnick")))
    @requires_setnick
    async def rnick(
        message: Message,
        server_id: int = 0,
        access_level: int = 0,
    ) -> None:
        target_id, err = await _parse_nick_target(message, api)
        if err:
            await message.answer(err)
            return
        if target_id is None:
            await message.answer(_NICK_TARGET_ERR)
            return

        blocked = await _staff_nick_blocked_message(target_id, server_id, names)
        if blocked:
            await message.answer(blocked, disable_mentions=1)
            return

        if not await UserRepository.has_nickname(target_id, server_id):
            link = await names.link_user(target_id, server_id)
            await message.answer(
                f"❌ У {link} нет никнейма на этом сервере.",
                disable_mentions=1,
            )
            return

        old_nick = await UserRepository.get_nickname(target_id, server_id) or ""
        await UserRepository.clear_nickname(target_id, server_id)
        actor = await names.format_setnick_actor(message.from_id or 0, server_id)
        target_link = await names.link_user(target_id, server_id)
        await message.answer(
            f"{actor} снял никнейм '{old_nick}' у {target_link}.",
            disable_mentions=1,
        )
        await action_logger.log_user(
            "rnick",
            message.from_id,
            f"id{target_id} ← {old_nick}",
            "Снят",
            source_peer_id=message.peer_id,
        )

    @bot.on.message(text=dual("staff") + dual("admins"))
    @requires_level(AccessLevel.PGS, require_registered=True)
    async def staff(
        message: Message,
        server_id: int = 0,
        access_level: int = 0,
    ) -> None:
        text = await format_staff_list(server_id, api)
        await message.answer(text, disable_mentions=1)

    @bot.on.message(FuncRule(lambda m: matches_who(m.text or "")))
    @requires_public
    async def who(
        message: Message,
        server_id: int = 0,
        access_level: int = 0,
    ) -> None:
        target_id: int | None = None
        if message.reply_message and message.reply_message.from_id > 0:
            target_id = message.reply_message.from_id
        elif message.from_id:
            target_id = message.from_id

        if not target_id:
            await message.answer("ℹ️ Ответьте на сообщение пользователя.")
            return

        card = await format_who_card(target_id, api, server_id)
        await message.answer(card, disable_mentions=1)

    @bot.on.message(text=dual("setlevel"))
    @requires_level(AccessLevel.ZGS)
    async def setlevel_usage(
        message: Message,
        server_id: int = 0,
        access_level: int = 0,
    ) -> None:
        max_lvl = AccessLevel.GA if await UserRepository.is_developer(message.from_id or 0) else AccessLevel.ZGA
        await message.answer(
            f"❌ Использование: /setlevel [vk.ru|ID|@user|ник] [0–{max_lvl}]\n"
            "Нельзя выдать другому уровень равный или выше своего; себя понизить нельзя."
        )

    @bot.on.message(text=dual_with_args("setlevel", "<target> <level>"))
    @requires_level(AccessLevel.ZGS)
    async def set_level(
        message: Message,
        target: str,
        level: str,
        server_id: int = 0,
        access_level: int = 0,
    ) -> None:
        is_dev = await UserRepository.is_developer(message.from_id)
        max_grant = AccessLevel.GA if is_dev else AccessLevel.ZGA

        try:
            new_level = int(level)
        except ValueError:
            await message.answer(f"❌ Уровень — число от 0 до {max_grant}.")
            return
        if new_level < 0 or new_level > max_grant:
            await message.answer(f"❌ Доступны уровни 0–{max_grant}.")
            return

        granter_level = access_level
        if is_dev:
            granter_level = AccessLevel.DEVELOPER
        if new_level > granter_level:
            await message.answer("❌ Нельзя выдать уровень выше своего.")
            return

        resolver = VKResolver(api, server_id)
        resolved, hint = await resolver.resolve_with_hint(target.strip(), server_id)
        if hint:
            await message.answer(hint, disable_mentions=1)
            return
        if not resolved:
            await message.answer(
                "❌ Пользователь не найден.\n"
                "Укажите VK-ссылку, id или ник из /setnick."
            )
            return

        if resolved.vk_id != message.from_id and new_level >= granter_level:
            await message.answer("❌ Нельзя выдать уровень равный или выше своего.")
            return

        if resolved.vk_id == message.from_id and new_level < granter_level:
            await message.answer("❌ Нельзя понизить свой уровень ниже текущего.")
            return

        old_level = await UserRepository.get_access_level(resolved.vk_id, server_id)

        if old_level <= 0 and new_level > 0:
            from services.panel_login import PANEL_BASE_URL

            assign_url = (
                f"{PANEL_BASE_URL}/assign?type=staff"
                if PANEL_BASE_URL
                else "/assign?type=staff"
            )
            await message.answer(
                "❌ У пользователя не было доступа следящего.\n"
                f"Назначьте через сайт: {assign_url}",
                disable_mentions=1,
            )
            return

        await UserRepository.ensure_user(
            vk_id=resolved.vk_id,
            username=resolved.username,
            added_by=message.from_id,
        )
        await UserRepository.set_access_level(
            vk_id=resolved.vk_id,
            server_id=server_id,
            level=new_level,
            granted_by=message.from_id,
        )

        nick_note = ""
        if new_level > 0 and old_level > 0:
            from services.staff_nickname_sync import sync_staff_nickname_tag

            updated_nick = await sync_staff_nickname_tag(
                resolved.vk_id,
                server_id,
                new_level,
            )
            if updated_nick:
                nick_note = f"\n🏷 Ник: {updated_nick}"

        def level_label(lvl: int) -> str:
            if lvl <= 0:
                return "нет доступа"
            return AccessChecker.level_name(lvl)

        granter = await names.link_user(message.from_id, server_id)
        target = await names.link_user(resolved.vk_id, server_id)
        result_text = (
            f"{granter} выдал {target} уровень доступа "
            f"{level_label(new_level)} [{new_level}], "
            f"было {level_label(old_level)} [{old_level}]"
        )
        log_detail = "Снят" if new_level == 0 else "Выдан"
        await message.answer(
            f"✅ {result_text}{nick_note}",
            disable_mentions=1,
        )
        await action_logger.log_user(
            "setlevel",
            message.from_id,
            f"id{resolved.vk_id} → ур. {new_level}",
            log_detail,
            source_peer_id=message.peer_id,
        )

    @bot.on.message(FuncRule(lambda m: matches_cmd(m.text or "", "setsphere")))
    @requires_level(AccessLevel.PGS)
    async def set_sphere(
        message: Message,
        server_id: int = 0,
        access_level: int = 0,
    ) -> None:
        args = strip_cmd(message.text or "", "setsphere")
        reply_id = (
            message.reply_message.from_id
            if message.reply_message and message.reply_message.from_id > 0
            else None
        )
        if reply_id:
            payload = (args or "").strip()
            target_ref = str(reply_id)
        else:
            if not args.strip():
                await message.answer(_SETSPHERE_USAGE)
                return
            resolver_tmp = VKResolver(api, server_id)
            target_ref = resolver_tmp.extract_reference(args)
            payload = args.replace(target_ref, "", 1).strip() if target_ref else ""
        if not payload:
            await message.answer(_SETSPHERE_USAGE)
            return

        main_text, senior_text = _split_setsphere_payload(payload)
        if not main_text:
            await message.answer(_SETSPHERE_USAGE)
            return

        try:
            spheres = validate_spheres(parse_sphere_tokens(main_text), access_level=access_level)
        except ValueError as exc:
            await message.answer(f"❌ {exc}")
            return

        senior_spheres: list[str] | None = None
        is_senior: bool | None = None
        if senior_text is not None:
            cleared = senior_text.strip().lower() in ("", "-", "нет", "0", "off")
            if cleared:
                is_senior = False
                senior_spheres = []
            else:
                try:
                    senior_spheres = validate_spheres(
                        parse_sphere_tokens(senior_text),
                        access_level=AccessLevel.SUPERVISOR,
                    )
                except ValueError as exc:
                    await message.answer(f"❌ {exc}")
                    return
                is_senior = True

        resolver = VKResolver(api, server_id)
        resolved, hint = await resolver.resolve_with_hint(target_ref.strip(), server_id)
        if hint:
            await message.answer(hint, disable_mentions=1)
            return
        if not resolved:
            await message.answer(
                "❌ Пользователь не найден.\n"
                "Укажите VK-ссылку, id, ник из /setnick или ответьте на сообщение."
            )
            return

        if resolved.vk_id != message.from_id and access_level < AccessLevel.ZGS:
            await message.answer("❌ Сменить сферу другому можно только с уровня ЗГС.")
            return

        ok, result = await set_staff_spheres_via_panel(
            actor_vk_id=message.from_id or 0,
            server_id=server_id,
            vk_id=resolved.vk_id,
            spheres=spheres,
            is_senior=is_senior,
            senior_spheres=senior_spheres,
        )
        if not ok:
            await message.answer(f"❌ {result}")
            return

        nick_note = ""
        try:
            from services.staff_nickname_sync import sync_staff_nickname_tag

            updated_nick = await sync_staff_nickname_tag(
                resolved.vk_id,
                server_id,
                await UserRepository.get_access_level(resolved.vk_id, server_id),
            )
            if updated_nick:
                nick_note = f"\n🏷 Ник: {updated_nick}"
        except Exception:
            logger.debug("sync_staff_nickname_tag after set_sphere failed", exc_info=True)

        granter = await names.link_user(message.from_id or 0, server_id)
        target_link = await names.link_user(resolved.vk_id, server_id)
        sphere_text = format_spheres_display(spheres)
        msg = f"✅ {granter} обновил сферы у {target_link}: {sphere_text}{nick_note}"
        if is_senior and senior_spheres:
            msg += f"\n👑 Старший / совмещение: {format_spheres_display(senior_spheres)}"
        elif is_senior is False:
            msg += "\n👑 Старший / совмещение снято"
        await message.answer(msg, disable_mentions=1)
        await action_logger.log_user(
            "set_sphere",
            message.from_id,
            f"id{resolved.vk_id} → сферы {sphere_text}{' | ' + format_spheres_display(senior_spheres) if senior_spheres else ''}",
            "Обновлены сферы",
            source_peer_id=message.peer_id,
        )

    @bot.on.message(FuncRule(lambda m: is_user_info_cmd(m.text or "")))
    @requires_public
    async def user_info(message: Message, server_id: int = 0) -> None:
        target_id, err = await _parse_profile_target(message, api, "info")
        if err:
            await message.answer(err)
            return
        if target_id is None:
            await message.answer(_NICK_TARGET_ERR)
            return

        card = await format_user_profile_card(target_id, api, server_id)
        await message.answer(card, disable_mentions=True)
