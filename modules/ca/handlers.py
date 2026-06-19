"""Доступ ЦА: /setca, /regrole, /raccess."""

from __future__ import annotations

import logging

from vkbottle import API, Keyboard, OpenLink
from vkbottle.bot import Bot, Message

from database.models.role_chat import ForumRoleKey
from database.models.user import AccessLevel
from database.repository.congress_repo import CongressRepository
from database.repository.forum_role_repo import ForumRoleRepository
from database.repository.user_repo import UserRepository
from middlewares.access import requires_level
from middlewares.action_logger import ActionLogger
from middlewares.ca_access import requires_ca_scope
from middlewares.forum_access import requires_court_manager
from services.command_utils import dual, dual_args, dual_with_args, strip_cmd
from services.display_name import DisplayNameService
from services.panel_login import (
    build_login_url,
    check_rate_limit,
    panel_login_configured,
)
from services.self_access import revoke_accesses

_RACCESS_LABELS = {
    "судья": "⚖️ Судья",
    "лидер": "🛡 Лидер",
    "спикер конгресса": "🎙 Спикер конгресса",
    "вице-спикер конгресса": "🎖 Вице-спикер конгресса",
    "доступ след. ЦА": "👁 Доступ след. ЦА",
    "доступ ЦА": "🏛 Доступ ЦА",
}
from services.vk_resolver import VKResolver

logger = logging.getLogger(__name__)

_REGROLE_ALIASES: dict[str, str] = {
    "court": "court",
    "judge": "court",
    "суд": "court",
    "congress": "congress",
    "cong": "congress",
    "конгресс": "congress",
    "sledca": "sledca",
    "sledco": "sledca",
    "следца": "sledca",
    "следцa": "sledca",
    "leader": "leader",
    "leaders": "leader",
    "лидер": "leader",
    "лидеры": "leader",
    "руководство": "leader",
    "руководствoca": "leader",
    "руководствoца": "leader",
}


def _normalize_regrole_type(raw: str) -> str | None:
    key = raw.strip().lower().replace("_", "")
    return _REGROLE_ALIASES.get(key)


async def _register_congress_chat(
    message: Message,
    api: API,
    server_id: int,
    alias: str | None = None,
) -> None:
    if message.peer_id < 2_000_000_000:
        await message.answer("❌ Регистрация только в беседе конференции.")
        return

    title = None
    try:
        conv = await api.messages.get_conversations_by_id(peer_ids=[message.peer_id])
        if conv.items:
            title = conv.items[0].chat_settings.title
    except Exception as exc:
        logger.warning("Не удалось получить название беседы конгресса: %s", exc)

    try:
        normalized = await CongressRepository.register_chat(
            message.peer_id,
            message.from_id or 0,
            server_id,
            alias=alias,
            title=title,
        )
    except ValueError as exc:
        await message.answer(f"❌ {exc}")
        return

    await message.answer(
        f"✅ Беседа конгресса привязана.\n"
        f"Алиас /msg: {normalized}\n"
        f"Спикер и вице: /setnick, /kick, /msg {normalized} — только здесь.\n"
        f"Назначение: /setspeaker, /setvice"
    )


def register_ca(bot: Bot, api: API, action_logger: ActionLogger) -> None:
    resolver = VKResolver(api)
    names = DisplayNameService(api)

    @bot.on.message(text=dual("setca"))
    @requires_level(AccessLevel.ZGS)
    @requires_ca_scope
    async def setca_usage(
        message: Message,
        server_id: int = 0,
        access_level: int = 0,
    ) -> None:
        await message.answer(
            "❌ Использование: /setca [@user|ник|vk.ru] [off]\n"
            "Или ответом на сообщение: /setca [off]\n"
            "Выдаёт или снимает доступ ЦА (конгресс, суд, ур. 1–4)."
        )

    @bot.on.message(text=dual_args("setca"))
    @requires_level(AccessLevel.ZGS)
    @requires_ca_scope
    async def set_ca(
        message: Message,
        args: str | None = None,
        server_id: int = 0,
        access_level: int = 0,
    ) -> None:
        raw = strip_cmd(message.text or "", "setca")
        revoke = False
        target_args = raw

        if raw.lower().endswith(" off"):
            revoke = True
            target_args = raw[:-4].strip()
        elif raw.lower() == "off":
            revoke = True
            target_args = ""

        reply_id = (
            message.reply_message.from_id
            if message.reply_message and message.reply_message.from_id > 0
            else None
        )
        resolved, hint = await resolver.resolve_from_message_with_hint(
            target_args,
            reply_from_id=reply_id,
            server_id=server_id,
        )
        if hint:
            await message.answer(hint, disable_mentions=1)
            return
        if not resolved:
            await message.answer("❌ Пользователь не найден.")
            return

        await UserRepository.ensure_user(
            vk_id=resolved.vk_id,
            username=resolved.username,
            added_by=message.from_id,
        )
        await UserRepository.set_ca_access(
            resolved.vk_id,
            server_id,
            enabled=not revoke,
            granted_by=message.from_id,
        )
        link = await names.link_user(resolved.vk_id, server_id)
        if revoke:
            await message.answer(f"✅ {link} — доступ ЦА снят.", disable_mentions=1)
            action = "ca_access_revoke"
            detail = "Снят доступ ЦА"
        else:
            await message.answer(f"✅ {link} — выдан доступ ЦА.", disable_mentions=1)
            action = "ca_access_grant"
            detail = "Выдан доступ ЦА"

        await action_logger.log_user(
            action,
            message.from_id,
            f"id{resolved.vk_id}",
            detail,
            source_peer_id=message.peer_id,
        )

    async def _run_raccess(
        message: Message,
        *,
        target_args: str | None,
        server_id: int,
        access_level: int = 0,
    ) -> None:
        actor_id = message.from_id or 0
        if actor_id <= 0:
            return

        reply_id = (
            message.reply_message.from_id
            if message.reply_message and message.reply_message.from_id > 0
            else None
        )
        if not reply_id and not (target_args and target_args.strip()):
            await message.answer(
                "❌ /raccess [@user|ник] — снять роли с пользователя.\n"
                "Или ответом на его сообщение.\n"
                "Не с себя; нельзя снимать с уровня своего и выше."
            )
            return

        resolved, hint = await resolver.resolve_from_message_with_hint(
            target_args or "",
            reply_from_id=reply_id,
            server_id=server_id,
        )
        if hint:
            await message.answer(hint, disable_mentions=1)
            return
        if not resolved:
            await message.answer("❌ Пользователь не найден.")
            return

        target_id = resolved.vk_id
        if target_id == actor_id:
            await message.answer("❌ /raccess — только с другого пользователя, не с себя.")
            return

        actor_level = access_level or await UserRepository.get_access_level(
            actor_id, server_id
        )
        if not await UserRepository.is_developer(actor_id):
            if await UserRepository.is_developer(target_id):
                await message.answer("❌ Нельзя снять роли с разработчика.")
                return
            target_level = await UserRepository.get_access_level(target_id, server_id)
            if target_level >= actor_level:
                from middlewares.access import AccessChecker

                await message.answer(
                    "❌ Нельзя снять роли с пользователя своего уровня или выше.\n"
                    f"Ваш: {AccessChecker.level_name(actor_level)} ({actor_level}), "
                    f"у цели: {AccessChecker.level_name(target_level)} ({target_level})."
                )
                return

        removed = await revoke_accesses(target_id, server_id)
        if not removed:
            link = await names.link_user(target_id, server_id)
            await message.answer(
                f"❌ У {link} нечего снимать.\n"
                "Нет ролей: судья, лидер, спикер/вице, доступ ЦА / след. ЦА.",
                disable_mentions=1,
            )
            return

        link = await names.link_user(target_id, server_id)
        lines = [f"✅ {link} — снято:", ""]
        for item in removed:
            lines.append(f"• {_RACCESS_LABELS.get(item, item)}")
        await message.answer("\n".join(lines), disable_mentions=1)
        await action_logger.log_user(
            "raccess",
            actor_id,
            f"id{target_id}: {', '.join(removed)}",
            "Снято" if target_id == actor_id else f"Снято с id{target_id}",
            source_peer_id=message.peer_id,
        )

    @bot.on.message(text=dual("raccess"))
    @requires_level(AccessLevel.SUPERVISOR)
    @requires_ca_scope
    async def raccess_usage(
        message: Message,
        server_id: int = 0,
        access_level: int = 0,
    ) -> None:
        await _run_raccess(
            message, target_args=None, server_id=server_id, access_level=access_level
        )

    @bot.on.message(text=dual_args("raccess"))
    @requires_level(AccessLevel.SUPERVISOR)
    @requires_ca_scope
    async def raccess_target(
        message: Message,
        args: str | None = None,
        server_id: int = 0,
        access_level: int = 0,
    ) -> None:
        await _run_raccess(
            message, target_args=args, server_id=server_id, access_level=access_level
        )

    @bot.on.message(text=dual("regrole"))
    @requires_level(AccessLevel.ZGS)
    @requires_ca_scope
    async def regrole_usage(
        message: Message,
        server_id: int = 0,
        access_level: int = 0,
    ) -> None:
        await message.answer(
            "❌ Использование: /regrole [court|congress|sledca|leader]\n"
            "Примеры:\n"
            "• /regrole court — беседа судей\n"
            "• /regrole congress — конгресс (алиас /msg: /regcongress имя)\n"
            "• /regrole sledca — беседа след. ЦА (авто ур. 1 при входе)\n"
            "• /regrole leader — беседа руководства ЦА (лидеры)\n"
            "Алиасы: /regcourt, /regcongress, /regsledco"
        )

    @bot.on.message(text=dual_with_args("regrole", "<role_type>"))
    @requires_level(AccessLevel.ZGS)
    @requires_ca_scope
    async def regrole_type_only(
        message: Message,
        role_type: str,
        server_id: int = 0,
        access_level: int = 0,
    ) -> None:
        await _handle_regrole(
            message,
            api,
            action_logger,
            server_id,
            role_type=role_type,
            alias=None,
        )

    @bot.on.message(text=dual_with_args("regrole", "<role_type> <alias>"))
    @requires_level(AccessLevel.ZGS)
    @requires_ca_scope
    async def regrole_with_alias(
        message: Message,
        role_type: str,
        alias: str,
        server_id: int = 0,
        access_level: int = 0,
    ) -> None:
        await _handle_regrole(
            message,
            api,
            action_logger,
            server_id,
            role_type=role_type,
            alias=alias,
        )

    @bot.on.message(text=dual("regcourt"))
    @requires_court_manager
    async def regcourt_legacy(message: Message, server_id: int = 0) -> None:
        await _handle_regrole(
            message, api, action_logger, server_id, role_type="court", alias=None
        )

    @bot.on.message(text=dual("regsledco"))
    @requires_level(AccessLevel.ZGS)
    @requires_ca_scope
    async def regsledco_legacy(message: Message, server_id: int = 0) -> None:
        await _handle_regrole(
            message, api, action_logger, server_id, role_type="sledca", alias=None
        )

    @bot.on.message(text=dual("regcongress"))
    @requires_level(AccessLevel.ZGS)
    @requires_ca_scope
    async def regcongress_legacy(
        message: Message,
        server_id: int = 0,
        access_level: int = 0,
    ) -> None:
        await _register_congress_chat(message, api, server_id, alias=None)
        await action_logger.log_user(
            "regcongress",
            message.from_id,
            f"peer {message.peer_id}",
            "Беседа конгресса",
            source_peer_id=message.peer_id,
        )

    @bot.on.message(text=dual_with_args("regcongress", "<alias>"))
    @requires_level(AccessLevel.ZGS)
    @requires_ca_scope
    async def regcongress_alias_legacy(
        message: Message,
        alias: str,
        server_id: int = 0,
        access_level: int = 0,
    ) -> None:
        await _register_congress_chat(message, api, server_id, alias=alias)
        await action_logger.log_user(
            "regcongress",
            message.from_id,
            f"peer {message.peer_id}, алиас {alias}",
            "Беседа конгресса",
            source_peer_id=message.peer_id,
        )

    _PANEL_CMDS = ["/panel", "!panel", "/login", "!login", "/вход", "!вход"]

    @bot.on.message(text=_PANEL_CMDS)
    @requires_ca_scope
    async def panel_login(message: Message, server_id: int = 0) -> None:
        user_id = message.from_id
        if not user_id or user_id <= 0:
            return

        if message.peer_id != user_id:
            await message.answer(
                "Вход на сайт — только в личных сообщениях.\n"
                "Откройте бота и напишите /panel в ЛС."
            )
            return

        if not panel_login_configured():
            await message.answer(
                "Вход через бота сейчас недоступен.\n"
                "Обратитесь к администратору или войдите через Discord."
            )
            return

        if not check_rate_limit(user_id):
            await message.answer("Подождите полминуты и запросите ссылку снова.")
            return

        try:
            url = build_login_url(user_id)
        except RuntimeError as exc:
            await message.answer(f"❌ {exc}")
            return

        kb = Keyboard(inline=True)
        kb.add(OpenLink(link=url, label="Открыть портал"))

        await message.answer(
            "Вход на портал след. ЦА\n\n"
            "Нажмите кнопку ниже. Ссылка действует 5 минут и срабатывает один раз.\n\n"
            "Если Discord не привязан — это запасной способ входа. "
            "Откройте ссылку в том браузере, где будете работать с сайтом.",
            keyboard=kb,
        )
        await action_logger.log_user(
            "panel_login",
            user_id,
            "ЛС",
            "Запрос ссылки входа на панель",
        )


async def _handle_regrole(
    message: Message,
    api: API,
    action_logger: ActionLogger,
    server_id: int,
    *,
    role_type: str,
    alias: str | None,
) -> None:
    if message.peer_id < 2_000_000_000:
        await message.answer("❌ Команда только в беседах.")
        return

    kind = _normalize_regrole_type(role_type)
    if not kind:
        await message.answer(
            "❌ Неизвестный тип. Доступно: court, congress, sledca, leader"
        )
        return

    if kind == "leader":
        await ForumRoleRepository.save_role_chat(
            ForumRoleKey.LEADER,
            message.peer_id,
            message.from_id or 0,
            server_id,
        )
        await message.answer(
            "✅ Беседа руководства ЦА (лидеры) привязана.\n"
            "Участники отображаются в панели (раздел «Лидеры»).\n"
            "При выходе — снимается роль лидера."
        )
        await action_logger.log_user(
            "regleader",
            message.from_id,
            f"peer {message.peer_id}",
            "Беседа руководства ЦА",
            source_peer_id=message.peer_id,
        )
        return

    if kind == "court":
        await ForumRoleRepository.save_role_chat(
            ForumRoleKey.JUDGE,
            message.peer_id,
            message.from_id or 0,
            server_id,
        )
        await message.answer(
            "✅ Беседа судей привязана.\n"
            "При выходе роль судьи снимается автоматически."
        )
        await action_logger.log_user(
            "regcourt",
            message.from_id,
            f"peer {message.peer_id}",
            "Беседа судей (regrole)",
            source_peer_id=message.peer_id,
        )
        return

    if kind == "sledca":
        await ForumRoleRepository.save_role_chat(
            ForumRoleKey.SLED_CA,
            message.peer_id,
            message.from_id or 0,
            server_id,
        )
        await message.answer(
            "✅ Беседа след. ЦА привязана.\n"
            "При входе: ур. 1 (ПГС) + доступ ЦА.\n"
            "При выходе/кике — снимается."
        )
        await action_logger.log_user(
            "regsledca",
            message.from_id,
            f"peer {message.peer_id}",
            "Беседа след. ЦА",
            source_peer_id=message.peer_id,
        )
        return

    await _register_congress_chat(message, api, server_id, alias=alias)
    await action_logger.log_user(
        "regcongress",
        message.from_id,
        f"peer {message.peer_id}, алиас {alias or '—'}",
        "Беседа конгресса (regrole)",
        source_peer_id=message.peer_id,
    )
