"""Модерация: /kick, /poolkick."""

from __future__ import annotations

import json
import logging
import random

from vkbottle import API, GroupEventType
from vkbottle.bot import Bot, Message, MessageEvent

from database.models.user import AccessLevel
from database.repository.chat_repo import ChatRepository
from database.repository.user_repo import UserRepository
from database.spheres import GOV_STRUCTURES
from middlewares.access import AccessChecker, requires_level
from middlewares.congress_access import requires_chat_kick
from middlewares.action_logger import ActionLogger
from services.command_utils import dual, dual_with_args
from services.display_name import DisplayNameService
from services.moderation import ModerationService
from services.poolkick_flow_pending import (
    FoundPeerData,
    create_scope_session,
    get as get_poolkick_flow,
    pop as pop_poolkick_flow,
    set_phase as set_poolkick_flow_phase,
)
from services.poolkick_scan import (
    filter_peers_by_scope,
    main_spheres_from_found,
    scan_user_in_chats,
)
from services.poolkick_scope_keyboard import create_poolkick_scope_keyboard
from services.poolkick_sphere_pending import pop as pop_poolkick_sphere_pending
from services.poolkick_sphere_revoke import (
    apply_poolkick_access_choice,
    apply_poolkick_sphere_choice,
    prompt_poolkick_access_after_kick,
)
from services.role_chat_leave import handle_role_chat_leave, revoke_judge_on_court_kick
from services.staff_hierarchy import can_act_on_target
from services.staff_nickname import MINISTRY_NICK_TAGS, STRUCTURE_NICK_TAGS
from services.staff_spheres import format_spheres_display, pool_alias_to_sphere
from services.vk_resolver import VKResolver

logger = logging.getLogger(__name__)

_LIST_LIMIT = 15


def _parse_target_and_reason(args: str) -> tuple[str, str | None]:
    parts = args.strip().split(maxsplit=1)
    if not parts:
        return "", None
    target = VKResolver.extract_reference(parts[0])
    return target, parts[1] if len(parts) > 1 else None


def _parse_poolkick_args(args: str) -> tuple[str, str | None]:
    text = args.strip()
    if not text:
        return "", None
    parts = text.split()
    # Устаревший флаг «1» в конце — игнорируем (заменён кнопкой «из всех»)
    if parts and parts[-1] == "1":
        parts = parts[:-1]
    if not parts:
        return "", None
    target = VKResolver.extract_reference(parts[0])
    reason = " ".join(parts[1:]).strip() or None
    return target, reason


async def _can_kick_by_access(
    actor_vk_id: int,
    actor_level: int,
    target_vk_id: int,
    server_id: int,
) -> tuple[bool, str | None]:
    return await can_act_on_target(
        actor_vk_id,
        actor_level,
        target_vk_id,
        server_id,
        on_equal_or_higher="❌ Нельзя исключить пользователя своего уровня или выше.",
        on_developer="❌ Нельзя исключить разработчика.",
    )


async def _senior_poolkick_allowed(
    actor_vk_id: int,
    server_id: int,
    chat: object | None,
    *,
    access_level: int,
) -> tuple[bool, str | None]:
    if access_level >= AccessLevel.ZGS:
        return True, None

    if access_level < AccessLevel.SUPERVISOR:
        return False, "⛔ Недостаточно прав."

    if not chat:
        return False, "⛔ Беседа не зарегистрирована."

    is_senior, senior_spheres = await UserRepository.get_senior_status(
        actor_vk_id, server_id
    )
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


def _short_sphere(sphere: str) -> str:
    return (
        MINISTRY_NICK_TAGS.get(sphere)
        or STRUCTURE_NICK_TAGS.get(sphere)
        or sphere
    )


def _scope_label(scope: str, sphere: str | None) -> str:
    if scope == "all":
        return "все найденные"
    if scope == "this":
        return "только эта беседа"
    if scope == "gos_only":
        return "только гос"
    if scope == "sphere" and sphere:
        return f"только {_short_sphere(sphere)}"
    if scope == "sphere_gos" and sphere:
        return f"{_short_sphere(sphere)}+гос"
    return scope


def _payload_owner_ok(payload: dict, user_id: int) -> bool:
    owner = payload.get("owner")
    if owner is None:
        return False
    try:
        return int(owner) == int(user_id)
    except (TypeError, ValueError):
        return False


def register_administration(bot: Bot, api: API, action_logger: ActionLogger) -> None:
    moderation = ModerationService(api)
    names = DisplayNameService(api)

    async def _send_chat(
        peer_id: int,
        text: str,
        *,
        keyboard: str | None = None,
    ) -> None:
        kwargs: dict = {
            "peer_id": peer_id,
            "message": text,
            "random_id": random.randint(1, 2_000_000_000),
            "disable_mentions": 1,
        }
        if keyboard:
            kwargs["keyboard"] = keyboard
        try:
            await api.messages.send(**kwargs)
        except Exception as exc:
            logger.warning("poolkick send failed peer=%s: %s", peer_id, exc)
            raise

    class _ChatReply:
        def __init__(self, peer_id: int) -> None:
            self.peer_id = peer_id

        async def answer(self, text: str, **kwargs: object) -> None:
            keyboard = kwargs.get("keyboard")
            await _send_chat(
                self.peer_id,
                text,
                keyboard=str(keyboard) if keyboard else None,
            )

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

    async def _run_poolkick_for_peers(
        *,
        message: Message,
        actor_id: int,
        access_level: int,
        server_id: int,
        target_vk_id: int,
        reason: str | None,
        peers: list[FoundPeerData],
        scope_label: str,
        pool_id: int | None,
        flow_token: str,
    ) -> None:
        if not peers:
            await message.answer("❌ Нет бесед для исключения в выбранном scope.")
            return

        report = await moderation.pullkick_peers(
            server_id=server_id,
            pool_id=pool_id,
            actor_vk_id=actor_id,
            target_vk_id=target_vk_id,
            reason=reason,
            peers=[(p.peer_id, p.title) for p in peers],
            scope_label=scope_label,
        )

        judge_revoked = False
        for item in report.results:
            if item.success:
                await _kick_announce(
                    item.peer_id,
                    target_id=target_vk_id,
                    actor_id=actor_id,
                    server_id=server_id,
                    reason=reason,
                )
                if not judge_revoked:
                    court_notice = await revoke_judge_on_court_kick(
                        item.peer_id,
                        target_vk_id,
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
                role_notice = await handle_role_chat_leave(
                    item.peer_id,
                    target_vk_id,
                    api,
                )
                if role_notice:
                    try:
                        await api.messages.send(
                            peer_id=item.peer_id,
                            message=role_notice,
                            random_id=0,
                            disable_mentions=1,
                        )
                    except Exception as exc:
                        logger.warning(
                            "role leave notice failed peer=%s: %s",
                            item.peer_id,
                            exc,
                        )

        target_link = await names.link_user(target_vk_id, server_id)
        await message.answer(
            report.format_message(
                target_label=target_link,
                pool_name=scope_label,
                reason=reason,
            ),
            disable_mentions=1,
        )
        await action_logger.log_user(
            "poolkick",
            actor_id,
            f"id{target_vk_id}, scope: {scope_label}"
            + (f", {reason}" if reason else ""),
            report.summary(),
            source_peer_id=message.peer_id,
        )

        if report.kicked <= 0:
            pop_poolkick_flow(flow_token, actor_id)
            return

        set_poolkick_flow_phase(flow_token, actor_id, "access")
        asked = await prompt_poolkick_access_after_kick(
            api=api,
            message=message,
            actor_vk_id=actor_id,
            server_id=server_id,
            target_vk_id=target_vk_id,
            flow_token=flow_token,
        )
        if not asked:
            pop_poolkick_flow(flow_token, actor_id)

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
            "Бот найдёт беседы и спросит, откуда исключить."
        )

    @bot.on.message(text=dual_with_args("poolkick", "<args>"))
    @requires_level(AccessLevel.SUPERVISOR)
    async def poolkick(
        message: Message,
        args: str,
        server_id: int = 0,
        access_level: int = 0,
    ) -> None:
        if message.peer_id < 2_000_000_000:
            await message.answer("❌ Команда только в беседах.")
            return

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
            reason = (args or "").strip() or None
            if reason and reason.endswith(" 1"):
                reason = reason[:-2].strip() or None
            elif reason == "1":
                reason = None
            target_raw = str(reply_id)
        else:
            target_raw, reason = _parse_poolkick_args(args)

        await chat.fetch_related("pool")
        allowed, err = await _senior_poolkick_allowed(
            message.from_id,
            server_id,
            chat,
            access_level=access_level,
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

        target_link = await names.link_user(resolved.vk_id, server_id)
        await message.answer(
            f"🔍 Ищу {target_link} в беседах…",
            disable_mentions=1,
        )

        scan = await scan_user_in_chats(
            api,
            server_id=server_id,
            target_vk_id=resolved.vk_id,
            actor_vk_id=message.from_id,
            access_level=access_level,
            source_peer_id=message.peer_id,
        )
        if not scan.found:
            await message.answer(
                f"❌ {target_link} не найден ни в одной зарегистрированной беседе "
                f"(проверено: {scan.scanned}).",
                disable_mentions=1,
            )
            return

        found_data = [
            FoundPeerData(
                peer_id=f.peer_id,
                title=f.title,
                sphere=f.sphere,
                pool_id=f.pool_id,
            )
            for f in scan.found
        ]
        token = create_scope_session(
            actor_id=message.from_id,
            server_id=server_id,
            target_vk_id=resolved.vk_id,
            peer_id=message.peer_id,
            reason=reason,
            source_sphere=scan.source_sphere,
            found=found_data,
            pool_id=chat.pool_id,
        )

        main_spheres = main_spheres_from_found(scan.found)
        if scan.source_sphere and scan.source_sphere in main_spheres:
            prefer = scan.source_sphere
        else:
            prefer = None

        has_this = any(f.peer_id == message.peer_id for f in scan.found)
        has_gos_only = any(f.sphere == GOV_STRUCTURES for f in scan.found) and not main_spheres

        lines = [
            f"🔍 Нашёл {target_link} в {len(scan.found)} беседах:",
            "",
        ]
        for item in scan.found[:_LIST_LIMIT]:
            sphere_tag = f" [{_short_sphere(item.sphere)}]" if item.sphere else ""
            lines.append(f"• {item.title}{sphere_tag}")
        if len(scan.found) > _LIST_LIMIT:
            lines.append(f"… и ещё {len(scan.found) - _LIST_LIMIT}")
        lines.extend(["", "Откуда исключить?"])

        await message.answer(
            "\n".join(lines),
            keyboard=create_poolkick_scope_keyboard(
                token,
                owner_id=message.from_id or 0,
                main_spheres=main_spheres,
                has_this=has_this,
                has_gos_only=has_gos_only,
                prefer_sphere=prefer,
            ),
            disable_mentions=1,
        )

    @bot.on.raw_event(GroupEventType.MESSAGE_EVENT, MessageEvent, blocking=False)
    async def poolkick_scope_callback(event: MessageEvent) -> None:
        payload = event.payload
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                return
        if not isinstance(payload, dict) or payload.get("cmd") != "pk_scope":
            return

        if not _payload_owner_ok(payload, event.user_id):
            await event.show_snackbar("⛔ Только автор команды.")
            return

        token = payload.get("token")
        scope = payload.get("scope")
        sphere = payload.get("sphere")
        if not token or not scope:
            await event.show_snackbar("❌ Запрос устарел.")
            return

        pending = get_poolkick_flow(str(token), event.user_id)
        if not pending or pending.phase != "scope":
            await event.show_snackbar("⏰ Время выбора истекло.")
            return

        if str(scope) == "cancel":
            pop_poolkick_flow(str(token), event.user_id)
            await event.show_snackbar("Отменено.")
            try:
                await _ChatReply(pending.peer_id).answer("ℹ️ Poolkick отменён.")
            except Exception:
                pass
            return

        from services.poolkick_scan import FoundChat

        found_chats = [
            FoundChat(
                peer_id=p.peer_id,
                title=p.title,
                alias=None,
                sphere=p.sphere,
                pool_id=p.pool_id,
            )
            for p in pending.found
        ]
        selected = filter_peers_by_scope(
            found_chats,
            scope=str(scope),
            source_peer_id=pending.peer_id,
            sphere_key=str(sphere) if sphere else None,
        )
        if not selected:
            await event.show_snackbar("❌ Нет бесед в этом scope.")
            return

        label = _scope_label(str(scope), str(sphere) if sphere else None)
        # show_snackbar уже закрывает callback — send_empty_answer не нужен
        await event.show_snackbar(f"Кикаю: {label} ({len(selected)})…")

        selected_data = [
            FoundPeerData(
                peer_id=s.peer_id,
                title=s.title,
                sphere=s.sphere,
                pool_id=s.pool_id,
            )
            for s in selected
        ]
        actor_level = await AccessChecker.get_level(
            event.user_id, pending.server_id
        )
        reply = _ChatReply(pending.peer_id)
        try:
            await _run_poolkick_for_peers(
                message=reply,  # type: ignore[arg-type]
                actor_id=event.user_id,
                access_level=actor_level,
                server_id=pending.server_id,
                target_vk_id=pending.target_vk_id,
                reason=pending.reason,
                peers=selected_data,
                scope_label=label,
                pool_id=pending.pool_id,
                flow_token=str(token),
            )
        except Exception as exc:
            logger.exception(
                "poolkick scope failed token=%s target=%s: %s",
                token,
                pending.target_vk_id,
                exc,
            )
            try:
                await reply.answer(
                    f"❌ Ошибка poolkick ({label}): {exc}"
                )
            except Exception:
                pass

    @bot.on.raw_event(GroupEventType.MESSAGE_EVENT, MessageEvent, blocking=False)
    async def poolkick_access_callback(event: MessageEvent) -> None:
        payload = event.payload
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                return
        if not isinstance(payload, dict) or payload.get("cmd") != "pk_access":
            return

        if not _payload_owner_ok(payload, event.user_id):
            await event.show_snackbar("⛔ Только автор команды.")
            return

        token = payload.get("token")
        choice = payload.get("choice")
        if not token or not choice:
            await event.show_snackbar("❌ Запрос устарел.")
            return

        pending = get_poolkick_flow(str(token), event.user_id)
        if not pending or pending.phase != "access":
            await event.show_snackbar("⏰ Время выбора истекло.")
            return

        source_sphere = pending.source_sphere
        pop_poolkick_flow(str(token), event.user_id)

        actor_level = await AccessChecker.get_level(
            event.user_id, pending.server_id
        )
        reply = _ChatReply(pending.peer_id)

        try:
            ok, detail = await apply_poolkick_access_choice(
                actor_vk_id=event.user_id,
                actor_level=actor_level,
                server_id=pending.server_id,
                target_vk_id=pending.target_vk_id,
                choice=str(choice),
                peer_id=pending.peer_id,
                message=reply,
                source_sphere=source_sphere,
            )
        except Exception as exc:
            logger.exception("poolkick access failed: %s", exc)
            await event.show_snackbar("❌ Ошибка обработки.")
            try:
                await reply.answer(f"❌ Ошибка: {exc}")
            except Exception:
                pass
            return

        if choice == "spheres" and detail == "Выбор сферы.":
            await event.show_snackbar("Выберите сферу.")
            return

        target_link = await names.link_user(
            pending.target_vk_id, pending.server_id
        )
        text = (
            f"✅ {target_link} — {detail}"
            if ok
            else f"❌ {detail}"
        )
        try:
            await reply.answer(text)
        except Exception as exc:
            logger.warning("poolkick access reply failed: %s", exc)
        await event.show_snackbar("Готово." if ok else "Ошибка.")

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

        if not _payload_owner_ok(payload, event.user_id):
            await event.show_snackbar("⛔ Только автор команды.")
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
            await _ChatReply(pending.peer_id).answer("ℹ️ Сферы не изменены.")
            await event.show_snackbar("Ок.")
            return

        pending = pop_poolkick_sphere_pending(token, event.user_id)
        if not pending:
            await event.show_snackbar("⏰ Время выбора истекло.")
            return

        actor_level = await AccessChecker.get_level(
            event.user_id, pending.server_id
        )

        combo_sphere = payload.get("sphere")
        if combo_sphere is not None:
            combo_sphere = str(combo_sphere)

        ok, detail = await apply_poolkick_sphere_choice(
            actor_vk_id=event.user_id,
            actor_level=actor_level,
            server_id=pending.server_id,
            target_vk_id=pending.target_vk_id,
            choice=str(choice),
            combo_sphere=combo_sphere,
        )
        reply = _ChatReply(pending.peer_id)
        if ok:
            target_link = await names.link_user(
                pending.target_vk_id, pending.server_id
            )
            await reply.answer(f"✅ {target_link} — {detail}")
            await event.show_snackbar("Готово.")
        else:
            await reply.answer(f"❌ {detail}")
            await event.show_snackbar("Ошибка.")
