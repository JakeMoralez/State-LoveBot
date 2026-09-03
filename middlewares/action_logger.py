"""Логирование действий в беседу logs или ЛС администратора."""

from __future__ import annotations

import logging
import random
import re
from dataclasses import dataclass
from datetime import datetime

from vkbottle import API

from config.settings import DEFAULT_SERVER_ID, DEFAULT_SERVER_SLUG, LOG_CHAT_ID, MAIN_ADMIN_ID
from database.repository.chat_repo import ChatRepository
from database.repository.chat_settings_repo import ChatSettingsRepository
from database.repository.server_repo import ServerRepository
from database.repository.user_repo import UserRepository
from middlewares.access import AccessChecker
from services.chat_admin import ChatAdminService
from services.chat_settings_ui import CHAT_SETTINGS
from services.display_name import DisplayNameService

logger = logging.getLogger(__name__)

_THREAD_ACTIONS = frozenset({
    "close_thread",
    "open_thread",
    "pin_thread",
    "unpin_thread",
    "thread_info",
    "toggle_open_close",
})

_USER_TARGET_ACTIONS = frozenset({
    "add_user",
    "remove_user",
    "make_admin",
    "make_judge",
    "add_court",
    "add_leader",
    "deluser",
    "kick",
    "invite",
    "poolkick",
    "mute",
    "unmute",
    "setlevel",
    "set_sphere",
    "setnick",
    "reg_staff",
    "rnick",
    "remove_judge",
    "remove_leader",
    "set_post",
    "raccess",
    "setca",
    "set_speaker",
    "set_vice",
})

_ACTION_VERB_SUCCESS: dict[str, str] = {
    "kick": "исключил",
    "invite": "добавил в беседу",
    "poolkick": "исключил из пула",
    "mute": "выдал мут",
    "unmute": "снял мут",
    "setnick": "установил ник",
    "rnick": "снял ник",
    "setlevel": "изменил уровень",
    "set_sphere": "изменил сферы",
    "reg_staff": "назначил следящего",
    "deluser": "удалил из БД",
    "add_leader": "назначил лидера",
    "remove_leader": "снял с лидера",
    "remove_judge": "снял судью",
    "add_court": "назначил судью",
    "set_post": "изменил должность",
    "raccess": "снял роли",
    "setca": "изменил доступ ЦА",
    "set_speaker": "назначил спикером",
    "set_vice": "назначил вице-спикером",
    "pin_message": "закрепил сообщение",
    "unpin_message": "открепил сообщение",
    "delete_message": "удалил сообщение",
    "close_thread": "закрыл тему",
    "open_thread": "открыл тему",
    "pin_thread": "закрепил тему",
    "unpin_thread": "открепил тему",
    "thread_info": "запросил инфо о теме",
    "stitle": "переименовал беседу в",
    "chatsettings": "изменил настройку",
    "regchat": "зарегистрировал беседу",
    "unregchat": "отвязал беседу от пула",
    "regchat_logs": "назначил беседу логов",
    "create_pool": "создал пул",
    "pool_msg": "отправил оповещение в пул",
    "regcourt": "зарегистрировал беседу судей",
    "regsledca": "зарегистрировал беседу след. ЦА",
    "regleader": "зарегистрировал беседу руководства ЦА",
    "regcongress": "зарегистрировал беседу конгресса",
    "panel_login": "запросил вход на портал",
    "role_leave": "снял роли при выходе",
    "forum_check": "проверил форум",
    "sync_judges": "синхронизировал судей",
    "claimfill": "заполнил claim",
    "court_form_submit": "отправил форму суда",
    "court_form_accept": "принял форму суда",
    "court_form_reject": "отклонил форму суда",
    "editmydiscord": "изменил Discord",
    "editmyforum": "изменил форум",
    "ca_access_grant": "выдал доступ ЦА",
    "ca_access_revoke": "снял доступ ЦА",
    "add_user": "добавил пользователя",
    "remove_user": "удалил пользователя",
    "make_admin": "назначил админом",
    "make_judge": "назначил судьёй",
}

_ACTION_VERB_FAIL: dict[str, str] = {
    "kick": "не смог исключить",
    "invite": "не смог добавить в беседу",
    "poolkick": "не смог исключить из пула",
    "mute": "не смог выдать мут",
    "unmute": "не смог снять мут",
    "setnick": "не смог установить ник",
    "rnick": "не смог снять ник",
    "setlevel": "не смог изменить уровень",
    "set_sphere": "не смог изменить сферы",
    "reg_staff": "не смог назначить следящего",
    "deluser": "не смог удалить из БД",
    "add_leader": "не смог назначить лидера",
    "remove_leader": "не смог снять с лидера",
    "close_thread": "не смог закрыть тему",
    "open_thread": "не смог открыть тему",
    "pin_thread": "не смог закрепить тему",
    "unpin_thread": "не смог открепить тему",
    "forum_check": "ошибка проверки форума",
    "sync_judges": "ошибка синхронизации судей",
}

_ACTION_TITLES: dict[str, str] = {
    "kick": "исключение из беседы",
    "invite": "добавление в беседу",
    "poolkick": "исключение из пула",
    "mute": "мут",
    "unmute": "снятие мута",
    "setlevel": "изменение уровня",
    "set_sphere": "изменение сфер",
    "reg_staff": "назначение следящего",
    "setnick": "установка никнейма",
    "rnick": "снятие никнейма",
    "chatsettings": "настройки беседы",
    "stitle": "переименование беседы",
    "panel_login": "вход на портал",
    "setca": "доступ ЦА",
    "ca_access_grant": "выдача доступа ЦА",
    "ca_access_revoke": "снятие доступа ЦА",
    "raccess": "снятие ролей",
    "add_court": "назначение судьи",
    "add_leader": "назначение лидера",
    "remove_judge": "снятие судьи",
    "remove_leader": "снятие лидера",
    "set_post": "должность судьи",
    "deluser": "удаление из БД",
    "regchat": "регистрация беседы",
    "unregchat": "отвязка беседы",
    "regchat_logs": "беседа логов",
    "create_pool": "создание пула",
    "pool_msg": "оповещение в пул",
    "regcourt": "беседа судей",
    "regsledca": "беседа след. ЦА",
    "regleader": "беседа руководства ЦА",
    "regcongress": "беседа конгресса",
    "set_speaker": "спикер конгресса",
    "set_vice": "вице-спикер конгресса",
    "pin_message": "закрепление сообщения",
    "unpin_message": "открепление сообщения",
    "delete_message": "удаление сообщения",
    "close_thread": "закрытие темы",
    "open_thread": "открытие темы",
    "pin_thread": "закрепление темы",
    "unpin_thread": "открепление темы",
    "thread_info": "инфо о теме",
    "court_form_submit": "форма суда",
    "court_form_accept": "принятие формы",
    "court_form_reject": "отклонение формы",
    "role_leave": "снятие роли при выходе",
    "forum_check": "проверка форума",
    "sync_judges": "синхронизация судей",
    "claimfill": "claimfill",
    "editmydiscord": "изменение Discord",
    "editmyforum": "изменение форума",
}

_VK_ID_RE = re.compile(r"\bid(\d+)\b", re.IGNORECASE)
_CMID_RE = re.compile(r"\bcmid\s+(\d+)\b", re.IGNORECASE)
_THREAD_RE = re.compile(r"^Тема\s+(\d+)", re.IGNORECASE)
_MUTE_DURATION_RE = re.compile(r"^(\d+)s$", re.IGNORECASE)
_SETTING_SLUG_RE = re.compile(r"^([a-zA-Z]+)=(.+)$")

_CHAT_SETTING_BY_SLUG = {setting.slug: setting for setting in CHAT_SETTINGS.values()}


@dataclass
class _NarrativeParts:
    main: str
    change_line: str | None = None


class ActionLogger:
    def __init__(self, api: API) -> None:
        self.api = api
        self.names = DisplayNameService(api)

    async def _resolve_server_id(self, source_peer_id: int | None) -> int | None:
        if source_peer_id and source_peer_id >= 2_000_000_000:
            chat = await ChatRepository.get_by_peer_id(source_peer_id)
            if chat:
                return chat.server_id
        default = await ServerRepository.get_by_id(DEFAULT_SERVER_ID)
        if default:
            return default.id
        by_slug = await ServerRepository.get_by_slug(DEFAULT_SERVER_SLUG)
        return by_slug.id if by_slug else None

    async def _resolve_log_peer(self, source_peer_id: int | None = None) -> int | None:
        server_ids: list[int] = []
        if source_peer_id and source_peer_id >= 2_000_000_000:
            chat = await ChatRepository.get_by_peer_id(source_peer_id)
            if chat:
                server_ids.append(chat.server_id)

        default = await ServerRepository.get_by_id(DEFAULT_SERVER_ID)
        if not default:
            default = await ServerRepository.get_by_slug(DEFAULT_SERVER_SLUG)
        if default and default.id not in server_ids:
            server_ids.append(default.id)

        for server_id in server_ids:
            peer = await ServerRepository.get_log_peer_id(server_id)
            if peer:
                return peer

        fallback = MAIN_ADMIN_ID or LOG_CHAT_ID
        return fallback if fallback else None

    async def _log_actor_label(self, vk_id: int, server_id: int | None = None) -> str:
        nick = await self.names.get_ping_nickname(vk_id, server_id)
        if nick:
            return nick
        full = await self.names.get_vk_full_name(vk_id)
        if full:
            return full
        if server_id:
            level = await UserRepository.get_access_level(vk_id, server_id)
            if level:
                return AccessChecker.level_name(level)
        return f"id{vk_id}"

    async def _short_user(self, vk_id: int, server_id: int | None = None) -> str:
        return await self._log_actor_label(vk_id, server_id)

    async def format_user(self, vk_id: int, server_id: int | None = None) -> str:
        return await self._log_actor_label(vk_id, server_id)

    async def _compact_user_label(self, vk_id: int, server_id: int | None) -> str:
        return await self._log_actor_label(vk_id, server_id)

    async def _enrich_ids_in_text(
        self,
        text: str,
        server_id: int | None,
    ) -> str:
        if not text:
            return "—"

        seen: set[int] = set()

        async def _replace(match: re.Match[str]) -> str:
            vk_id = int(match.group(1))
            if vk_id in seen:
                return match.group(0)
            seen.add(vk_id)
            return await self._compact_user_label(vk_id, server_id)

        result = text
        for match in list(_VK_ID_RE.finditer(text)):
            replacement = await _replace(match)
            result = result.replace(match.group(0), replacement, 1)
        return result

    @staticmethod
    def _split_target_and_extra(target_info: str) -> tuple[str, str | None]:
        if " → " in target_info:
            main, extra = target_info.split(" → ", 1)
            return main.strip(), extra.strip()
        if " ← " in target_info:
            main, extra = target_info.split(" ← ", 1)
            return main.strip(), extra.strip()

        lowered = target_info.lower()
        for sep in (", причина:", ", пул ", ", алиас ", " | "):
            idx = lowered.find(sep)
            if idx != -1:
                main = target_info[:idx].strip()
                extra = target_info[idx + 1 :].strip()
                return main, extra
        return target_info.strip(), None

    async def _log_source_short(self, source_peer_id: int | None) -> str:
        if not source_peer_id or source_peer_id < 2_000_000_000:
            return "ЛС бота"

        chat_id = source_peer_id - 2_000_000_000
        chat = await ChatRepository.get_by_peer_id(source_peer_id)
        title = ""
        alias = ""
        if chat:
            title = (chat.title or "").strip()
            alias = (chat.alias or "").strip()
        if not title:
            try:
                conv = await self.api.messages.get_conversations_by_id(
                    peer_ids=[source_peer_id]
                )
                if conv.items:
                    title = (conv.items[0].chat_settings.title or "").strip()
            except Exception as exc:
                logger.debug("log source title fetch failed peer=%s: %s", source_peer_id, exc)
        if not title:
            title = f"Беседа #{chat_id}"
        if alias:
            return f"«{title}» ({alias})"
        return f"«{title}»"

    @staticmethod
    def _is_failure(result: str) -> bool:
        low = result.strip().lower()
        if not low:
            return False
        if low.startswith("ошибка"):
            return True
        if low in {"не найден", "fail", "error"}:
            return True
        if "не удалось" in low or "не найден" in low:
            return True
        if low == "ok" or low.startswith("ok "):
            return False
        if any(word in low for word in ("ошибка", "error", "fail")):
            return True
        return False

    @staticmethod
    def _failure_detail(result: str) -> str:
        low = result.lower()
        if low.startswith("ошибка:"):
            return result.split(":", 1)[1].strip()
        if low.startswith("ошибка "):
            return result[7:].strip()
        return result.strip()

    @staticmethod
    def _format_mute_duration(raw: str) -> str:
        match = _MUTE_DURATION_RE.match(raw.strip())
        if not match:
            return raw
        seconds = int(match.group(1))
        if seconds <= 0:
            return "навсегда"
        return f"на {ChatAdminService.format_duration(seconds)}"

    @staticmethod
    def _parse_chat_setting(raw: str) -> tuple[str, str] | None:
        match = _SETTING_SLUG_RE.match(raw.strip())
        if not match:
            return None
        slug, value = match.group(1), match.group(2).strip()
        setting = _CHAT_SETTING_BY_SLUG.get(slug)
        if not setting:
            return slug, value
        label = ChatSettingsRepository.setting_value_label(setting.field, value)
        return setting.title, label

    @staticmethod
    def _format_thread_ref(text: str) -> str:
        match = _THREAD_RE.match(text.strip())
        if match:
            thread_id = match.group(1)
            rest = text[match.end() :].strip()
            if rest.startswith(":"):
                rest = rest[1:].strip()
            if rest:
                if len(rest) > 40:
                    rest = rest[:37] + "..."
                return f"#{thread_id} «{rest}»"
            return f"#{thread_id}"
        return text

    @staticmethod
    def _format_cmid_ref(text: str) -> str:
        match = _CMID_RE.search(text)
        if match:
            return f"#{match.group(1)}"
        return text

    def _narrate_log_line(
        self,
        action: str,
        actor: str,
        target_info: str,
        result: str,
        *,
        source: str,
        extra: str | None = None,
    ) -> _NarrativeParts:
        failed = self._is_failure(result)
        verb = (
            _ACTION_VERB_FAIL.get(action, f"ошибка: {_ACTION_TITLES.get(action, action)}")
            if failed
            else _ACTION_VERB_SUCCESS.get(
                action, _ACTION_TITLES.get(action, action.replace("_", " "))
            )
        )

        tails: list[str] = []
        change_line: str | None = None
        object_part = target_info

        if action == "chatsettings":
            if failed:
                verb = "не смог изменить"
            else:
                verb = "изменил"
            parsed = self._parse_chat_setting(target_info)
            if parsed:
                setting_title, value_label = parsed
                object_part = f"«{setting_title}» → {value_label}"
            else:
                object_part = target_info

        elif action == "stitle":
            object_part = f"«{target_info}»"

        elif action == "poolkick":
            if ", " in target_info:
                user_part, scope_part = target_info.split(", ", 1)
                object_part = user_part
                tails.append(scope_part)
            else:
                object_part = target_info

        elif action in ("mute",):
            parts = [part.strip() for part in target_info.split(",")]
            if parts:
                object_part = parts[0]
                for part in parts[1:]:
                    if _MUTE_DURATION_RE.match(part):
                        tails.append(self._format_mute_duration(part))
                    elif part:
                        tails.append(part)
            if extra:
                tails.append(extra)

        elif action in _USER_TARGET_ACTIONS:
            object_part = target_info
            if extra:
                if action == "setnick":
                    change_line = f"=> {extra}"
                elif action == "rnick":
                    change_line = f"{extra} => —"
                elif action == "setlevel":
                    change_line = f"=> {extra}"
                elif action == "set_sphere":
                    change_line = f"=> {extra}"
                elif action == "reg_staff":
                    change_line = f"=> {extra}"
                elif action == "kick":
                    tails.append(extra)
                elif action == "poolkick":
                    tails.append(extra)
                elif action == "raccess":
                    tails.append(extra)
                else:
                    tails.append(extra)

        elif action in _THREAD_ACTIONS:
            object_part = self._format_thread_ref(target_info)

        elif action in ("pin_message", "unpin_message", "delete_message"):
            object_part = self._format_cmid_ref(target_info)

        elif action == "panel_login":
            object_part = "из ЛС"

        elif action == "forum_check":
            object_part = target_info

        elif action == "sync_judges":
            object_part = target_info.replace("server=", "сервер ")

        elif action in ("regchat", "regcongress", "regcourt", "regsledca", "regleader"):
            object_part = target_info.replace("peer ", "peer_id ")
            if extra:
                tails.append(extra)

        elif action == "role_leave":
            object_part = target_info

        else:
            object_part = target_info
            if extra:
                tails.append(extra)

        if failed:
            fail_text = self._failure_detail(result)
            if fail_text and fail_text.lower() not in verb.lower():
                tails.append(fail_text)

        pieces = [actor, verb]
        if object_part and object_part != "—":
            pieces.append(object_part)
        if tails:
            pieces.append(" · ".join(tails))

        main = " ".join(pieces)
        main = f"{main} · {source}"
        if failed:
            main = f"❌ {main}"

        return _NarrativeParts(main=main, change_line=change_line)

    def _build_message(
        self,
        action: str,
        user_info: str,
        target_info: str,
        result: str,
        *,
        source: str,
        extra: str | None = None,
    ) -> str:
        timestamp = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
        narrative = self._narrate_log_line(
            action,
            user_info,
            target_info,
            result,
            source=source,
            extra=extra,
        )
        lines = [f"{timestamp} | {narrative.main}"]
        if narrative.change_line:
            lines.append(narrative.change_line)
        return "\n".join(lines)

    async def log_action(
        self,
        action: str,
        user_info: str,
        target_info: str,
        result: str,
        *,
        source_peer_id: int | None = None,
    ) -> None:
        log_peer = await self._resolve_log_peer(source_peer_id)
        if not log_peer:
            return

        main, extra = self._split_target_and_extra(target_info)
        msg = self._build_message(
            action,
            user_info,
            main,
            result,
            source=await self._log_source_short(source_peer_id),
            extra=extra,
        )
        try:
            await self.api.messages.send(
                peer_id=log_peer,
                message=msg,
                random_id=random.randint(1, 2_000_000_000),
                disable_mentions=1,
            )
        except Exception as exc:
            logger.error("Ошибка отправки лога: %s", exc)

    async def log_user(
        self,
        action: str,
        user_id: int,
        target_info: str,
        result: str,
        *,
        source_peer_id: int | None = None,
    ) -> None:
        server_id = await self._resolve_server_id(source_peer_id)
        user_info = await self._log_actor_label(user_id, server_id)

        main, extra = self._split_target_and_extra(target_info)
        main = await self._enrich_ids_in_text(main, server_id)
        if extra:
            extra = await self._enrich_ids_in_text(extra, server_id)

        log_peer = await self._resolve_log_peer(source_peer_id)
        if not log_peer:
            return

        msg = self._build_message(
            action,
            user_info,
            main,
            result,
            source=await self._log_source_short(source_peer_id),
            extra=extra,
        )
        try:
            await self.api.messages.send(
                peer_id=log_peer,
                message=msg,
                random_id=random.randint(1, 2_000_000_000),
                disable_mentions=1,
            )
        except Exception as exc:
            logger.error("Ошибка отправки лога: %s", exc)

    async def log(
        self,
        action: str,
        user_info: str,
        details: str,
        result: str,
        source_peer_id: int | None = None,
    ) -> None:
        await self.log_action(
            action,
            user_info,
            details,
            result,
            source_peer_id=source_peer_id,
        )
