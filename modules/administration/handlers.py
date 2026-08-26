"""Модерация: /kick, /poolkick."""

from __future__ import annotations

import json
import logging

from vkbottle import API
from vkbottle.bot import Bot, Message, MessageEvent
from vkbottle.tools.dev.mini_types.base.message import GroupEventType

from database.models.user import AccessLevel
from database.repository.chat_repo import ChatRepository
from database.repository.user_repo import UserRepository
from middlewares.access import AccessChecker, requires_level
from middlewares.congress_access import requires_chat_kick
from middlewares.action_logger import ActionLogger
from services.command_utils import dual, dual_with_args
from services.display_name import DisplayNameService
from services.moderation import ModerationService
from services.poolkick_sphere_pending import pop as pop_poolkick_sphere_pending
from services.poolkick_sphere_revoke import apply_poolkick_sphere_choice, handle_poolkick_sphere_after_kick
from services.role_chat_leave import revoke_judge_on_court_kick
from services.staff_hierarchy import can_act_on_target
from services.staff_spheres import format_spheres_display, pool_alias_to_sphere
from services.vk_resolver import VKResolver

logger = logging.getLogger(__name__)


def _parse_target_and_reason(args: str) -> tuple[str, str | None]:
    parts = args.strip().split(maxsplit=1)
    if not parts:
        return "", None
    target = VKResolver.extract_reference(parts[0])
    return target, parts[1] if len(parts) > 1 else None


def _parse_poolkick_args(args: str) -> tuple[str, str | None, bool]:
    """Цель, причина, флаг «1» = все зарегистрированные беседы сервера."""
    text = args.strip()
    if not text:
        return "", None, False
    parts = text.split()
    all_chats = False
    if parts and parts[-1] == "1":
        all_chats = True
        parts = parts[:-1]
    if not parts:
        return "", None, all_chats
    target = VKResolver.extract_reference(parts[0])
    reason = " ".join(parts[1:]).strip() or None
    return target, reason, all_chats


async def _can_kick_by_access(
    actor_vk_id: int,
    actor_level: int,
    target_vk_id: int,
    server_id: int,
) -> tuple[bool, str | None]:
    """Нельзя кикать равных/выше по уровню и разработчиков (кроме разработчика)."""
    return await can_act_on_target(
        actor_vk_id,
        actor_level,
        target_vk_id,
        server_id,
        on_equal_or_higher="❌ Нельзя исключить пользователя своего уровня или выше.",
        on_developer="❌ Нельзя исключить разработчика.",
    )


def _strip_all_chats_flag(text: str) -> tuple[str | None, bool]:
    """Для ответа на сообщение: причина и опциональный флаг 1 в конце."""
    parts = text.strip().split()
    if not parts:
        return None, False
    if parts[-1] == "1":
        reason = " ".join(parts[:-1]).strip() or None
        return reason, True
    return text.strip() or None, False


async def _senior_poolkick_allowed(
    actor_vk_id: int,
    server_id: int,
    chat: object | None,
    *,
    access_level: int,
    all_chats: bool,
) -> tuple[bool, str | None]:
    if access_level >= AccessLevel.ZGS:
        return True, None

    if access_level < AccessLevel.SUPERVISOR:
        return False, "⛔ Недостаточно прав."

    if all_chats:
        return False, "⛔ Старший следящий может кикать только в своей сфере."

    if not chat:
        return False, "⛔ Беседа не привязана к пулу."

    is_senior, senior_spheres = await UserRepository.get_senior_status(actor_vk_id, server_id)
    if not is_senior:
        return False, "⛔ Нужен уровень ЗГС или статус старшего следящего."
    if not senior_spheres:
        return False, "⛔ У вас не назначена сфера старшего."

    pool = getattr(chat, "pool", None)
    pool_name = getattr(pool, "name", None) if pool else None
    alias = getattr(chat, "alias", None)
    pool_sphere = pool_alias_to_sphere(alias, pool_name)
    if pool_sphere is None:
        return False, "⛔ Не удалось определить сферу этой беседы."
    if pool_sphere not in senior_spheres:
        return False, (
            "⛔ Эта беседа не в вашей сфере старшего.\n"
            f"Ваши сферы: {format_spheres_display(senior_spheres)}."
        )
    return True, None


def register_administration(bot: Bot, api: API, action_logger: ActionLogger) -> None:
    moderation = ModerationService(api)
    names = DisplayNameService(api)
    resolver = VKResolver(api)

    async def _kick_announce(
        peer_id: int,
        *,
        target_id: int,
        actor_id: int,
        server_id: int,
        reason: str | None,
    ) -> None:
        text = await names.format_kick_announce(
            target_id=target_id,
            actor_id=actor_id,
            server_id=server_id,
            reason=reason,
        )
        try:
            await api.messages.send(
                peer_id=peer_id,
                message=text,
                random_id=0,
                disable_mentions=1,
            )
        except Exception as exc:
            logger.warning("kick announce failed peer=%s: %s", peer_id, exc)

    @bot.on.message(text=dual("kick"))
    @requires_level(AccessLevel.SUPERVISOR)
    async def kick_usage(
        message: Message,
        server_id: int = 0,
        access_level: int = 0,
    ) -> None:
        await message.answer(
            "❌ /kick [@user] [причина]\n"
            "Или ответом: /kick причина"
        )

    @bot.on.message(text=dual_with_args("kick", "<args>"))
    @requires_chat_kick
    async def kick(
        message: Message,
        args: str,
        server_id: int = 0,
        access_level: int = 0,
    ) -> None:
        if message.peer_id < 2_000_000_000:
            await message.answer("❌ Команда только в беседах.")
            return

        reply_id = (
            message.reply_message.from_id
            if message.reply_message and message.reply_message.from_id > 0
            else None
        )

        cmd_resolver = VKResolver(api, server_id)
        if reply_id:
            resolved, _ = await cmd_resolver.resolve_with_hint(
                str(reply_id),
                server_id,
            )
            reason = args.strip() or None
        else:
            target_raw, reason = _parse_target_and_reason(args)
            resolved, _ = await cmd_resolver.resolve_with_hint(
                target_raw,
                server_id,
            )

        if not resolved:
            await message.answer("❌ Пользователь не найден.")
            return
        if resolved.vk_id == message.from_id:
            await message.answer("❌ Нельзя исключить самого себя.")
            return

        ok, err = await _can_kick_by_access(
            message.from_id,
            access_level,
            resolved.vk_id,
            server_id,
        )
        if not ok:
            await message.answer(err or "❌ Недостаточно прав для исключения.")
            return

        chat = await ChatRepository.get_by_peer_id(message.peer_id)
        pool_id = chat.pool_id if chat else None

        result = await moderation.kick(
            server_id=server_id,
            pool_id=pool_id,
            peer_id=message.peer_id,
            actor_vk_id=message.from_id,
            target_vk_id=resolved.vk_id,
            reason=reason,
        )

        if result.success:
            await _kick_announce(
                message.peer_id,
                target_id=resolved.vk_id,
                actor_id=message.from_id,
                server_id=server_id,
                reason=reason,
            )
            court_notice = await revoke_judge_on_court_kick(
                message.peer_id,
                resolved.vk_id,
                api,
            )
            if court_notice:
                try:
                    await api.messages.send(
                        peer_id=message.peer_id,
                        message=court_notice,
                        random_id=0,
                        disable_mentions=1,
                    )
                except Exception as exc:
                    logger.warning("court judge revoke notice failed: %s", exc)
            await action_logger.log_user(
                "kick",
                message.from_id,
                f"id{resolved.vk_id}" + (f", причина: {reason}" if reason else ""),
                "Исключён",
                source_peer_id=message.peer_id,
            )
        else:
            await message.answer(
                f"❌ Не удалось исключить.\n{result.error or 'нет прав админа у бота'}"
            )
            await action_logger.log_user(
                "kick",
                message.from_id,
                f"id{resolved.vk_id}",
                f"Ошибка: {(result.error or 'нет прав')[:80]}",
                source_peer_id=message.peer_id,
            )

    @bot.on.message(text=dual("poolkick"))
    @requires_level(AccessLevel.SUPERVISOR)
    async def poolkick_usage(
        message: Message,
        server_id: int = 0,
        access_level: int = 0,
    ) -> None:
        await message.answer(
            "❌ /poolkick [@user] [причина]\n"
            "Или ответом: /poolkick причина\n"
            "В конце «1» — все беседы сервера (только ЗГС)"
        )

    @bot.on.message(text=dual_with_args("poolkick", "<args>"))
    @requires_level(AccessLevel.SUPERVISOR)
    async def poolkick(
        message: Message,
        args: str,
        server_id: int = 0,
        access_level: int = 0,
    ) -> None:
        chat = await ChatRepository.get_by_peer_id(message.peer_id)
        if not chat:
            await message.answer("❌ Беседа не зарегистрирована.")
            return

        reply_id = (
            message.reply_message.from_id
            if message.reply_message and message.reply_message.from_id > 0
            else None
        )
        if reply_id:
            reason, all_chats = _strip_all_chats_flag(args)
            target_raw = str(reply_id)
        else:
            target_raw, reason, all_chats = _parse_poolkick_args(args)

        if not all_chats and not chat.pool_id:
            await message.answer("❌ Беседа не привязана к пулу.")
            return

        await chat.fetch_related("pool")
        allowed, err = await _senior_poolkick_allowed(
            message.from_id,
            server_id,
            chat,
            access_level=access_level,
            all_chats=all_chats,
        )
        if not allowed:
            await message.answer(err or "⛔ Недостаточно прав.")
            return

        resolved = await VKResolver(api, server_id).resolve_from_message(
            target_raw,
            reply_from_id=reply_id,
            server_id=server_id,
        )
        if not resolved:
            await message.answer("❌ Пользователь не найден.")
            return
        if resolved.vk_id == message.from_id:
            await message.answer("❌ Нельзя исключить самого себя.")
            return

        ok, err = await _can_kick_by_access(
            message.from_id,
            access_level,
            resolved.vk_id,
            server_id,
        )
        if not ok:
            await message.answer(err or "❌ Недостаточно прав для исключения.")
            return

        pool_name = chat.pool.name if chat.pool else str(chat.pool_id or "—")
        report = await moderation.pullkick(
            server_id=server_id,
            pool_id=chat.pool_id,
            actor_vk_id=message.from_id,
            target_vk_id=resolved.vk_id,
            reason=reason,
            all_chats=all_chats,
        )

        judge_revoked = False
        for item in report.results:
            if item.success:
                await _kick_announce(
                    item.peer_id,
                    target_id=resolved.vk_id,
                    actor_id=message.from_id,
                    server_id=server_id,
                    reason=reason,
                )
                if not judge_revoked:
                    court_notice = await revoke_judge_on_court_kick(
                        item.peer_id,
                        resolved.vk_id,
                        api,
                    )
                    if court_notice:
                        judge_revoked = True
                        try:
                            await api.messages.send(
                                peer_id=item.peer_id,
                                message=court_notice,
                                random_id=0,
                                disable_mentions=1,
                            )
                        except Exception as exc:
                            logger.warning(
                                "court judge revoke notice failed peer=%s: %s",
                                item.peer_id,
                                exc,
                            )

        target_link = await names.link_user(resolved.vk_id)
        await message.answer(
            report.format_message(
                target_label=target_link,
                pool_name=pool_name,
                reason=reason,
            ),
            disable_mentions=1,
        )
        scope = "все беседы сервера" if all_chats else f"пул {pool_name}"
        await action_logger.log_user(
            "poolkick",
            message.from_id,
            f"id{resolved.vk_id}, {scope}" + (f", {reason}" if reason else ""),
            report.summary(),
            source_peer_id=message.peer_id,
        )

        if report.kicked > 0:
            await handle_poolkick_sphere_after_kick(
                api=api,
                message=message,
                actor_vk_id=message.from_id,
                actor_level=access_level,
                server_id=server_id,
                target_vk_id=resolved.vk_id,
                chat=chat,
                kicked_count=report.kicked,
            )

    @bot.on.raw_event(GroupEventType.MESSAGE_EVENT, MessageEvent, blocking=False)
    async def poolkick_sphere_callback(event: MessageEvent) -> None:
        payload = event.payload
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                return
        if not isinstance(payload, dict) or payload.get("cmd") != "pk_sphere":
            return

        token = payload.get("token")
        choice = payload.get("choice")
        if not token or not choice:
            await event.show_snackbar("❌ Запрос устарел.")
            return

        if choice == "skip":
            pending = pop_poolkick_sphere_pending(token, event.user_id)
            if not pending:
                await event.show_snackbar("⏰ Время выбора истекло.")
                return
            await event.send_message("ℹ️ Сферы не изменены.")
            await event.send_empty_answer()
            return

        pending = pop_poolkick_sphere_pending(token, event.user_id)
        if not pending:
            await event.show_snackbar("⏰ Время выбора истекло.")
            return

        server_id = await AccessChecker.resolve_server_id(
            event.peer_id, event.user_id
        )
        actor_level = await AccessChecker.get_level(event.user_id, server_id)

        ok, detail = await apply_poolkick_sphere_choice(
            actor_vk_id=event.user_id,
            actor_level=actor_level,
            server_id=pending.server_id,
            target_vk_id=pending.target_vk_id,
            choice=str(choice),
        )
        if ok:
            target_link = await names.link_user(
                pending.target_vk_id, pending.server_id
            )
            await event.send_message(f"✅ {target_link} — {detail}", disable_mentions=1)
        else:
            await event.send_message(f"❌ {detail}")
        await event.send_empty_answer()
