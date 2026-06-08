# main.py
# -*- coding: utf-8 -*-
import asyncio
import logging
import traceback
import re
import json
import sqlite3
import time
import random
from datetime import datetime, timedelta

from vk_api import VkApi
from vk_api.bot_longpoll import VkBotLongPoll, VkBotEventType
from vk_api.utils import get_random_id
from vk_api.keyboard import VkKeyboard, VkKeyboardColor

from arizona_forum_async import ArizonaAPI

from config import (
    VK_GROUP_ID,
    VK_USER_TOKEN,
    VK_GROUP_TOKEN,
    FORUM_USER_AGENT,
    FORUM_COOKIES,
    LOG_CHAT_ID,
)
from users_db import (
    is_user_allowed,
    check_admin,
    get_username,
    is_attorney,
    is_leader,
    get_all_users,
    get_all_attorneys,
    get_all_leaders,
    save_role_chat,
    get_role_chat,
    get_all_role_chats, 
    get_all_role_chats_with_names,
    delete_role_chat
)
from database import init_db, DB_FILE
from logger import ActionLogger

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("bot.log"), logging.StreamHandler()],
)
logger = logging.getLogger(__name__)


class ForumBot:
    DUPLICATE_TIMEOUT = 10

    def __init__(self):
        logger.info("Инициализация бота...")

        # Основная сессия от группы (для сообщений, кнопок и т.д.)
        self.vk_session = VkApi(token=VK_GROUP_TOKEN)
        self.vk = self.vk_session.get_api()
        self.longpoll = VkBotLongPoll(self.vk_session, VK_GROUP_ID)

        # Дополнительная сессия от пользователя (для добавления в беседы)
        self.user_session = VkApi(token=VK_USER_TOKEN)
        self.user_vk = self.user_session.get_api()

        self.forum_api = ArizonaAPI(FORUM_USER_AGENT, FORUM_COOKIES)
        self.logger = ActionLogger(self.vk, LOG_CHAT_ID)

        # Загружаем ID бесед из БД в config (опционально)
        from users_db import get_role_chat

        self.leaders_cache = []
        self.leaders_cache_time = 0
        self.leaders_cache_chat_id = None  

        self.chat_names_cache = {}
        self.chat_names_cache_time = {}

        self.processed_events = {}
        self.user_data = {}

        logger.info("Бот инициализирован")

    # ================= VK УТИЛИТЫ =================

    def send_message(self, peer_id, message, keyboard=None):
        try:
            params = {
                "peer_id": peer_id,
                "message": message,
                "random_id": get_random_id(),
            }
            if keyboard:
                params["keyboard"] = keyboard.get_keyboard()
            self.vk.messages.send(**params)
        except Exception as e:
            logger.error(f"Ошибка отправки сообщения в {peer_id}: {e}")

    async def safe_edit(
        self, peer_id, cmid=None, message_id=None, new_text="", remove_keyboard=True
    ):
        """Безопасное редактирование сообщения (в беседах и личке)."""
        try:
            params = {"peer_id": peer_id, "message": new_text}

            if cmid is not None:
                params["conversation_message_id"] = cmid
            elif message_id is not None:
                params["message_id"] = message_id
            else:
                return False

            if remove_keyboard:
                params["keyboard"] = json.dumps({"buttons": [], "inline": True})

            self.vk.messages.edit(**params)
            await asyncio.sleep(0.2)
            return True

        except Exception as e:
            logger.error(f"safe_edit error: {e}")
            return False

    async def maybe_add_reaction(self, peer_id, cmid, reaction_chance=5):
        REACTION_IDS = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
        if random.randint(1, 100) > reaction_chance:
            return
        reaction_id = random.choice(REACTION_IDS)
        try:
            self.vk.messages.sendReaction(
                peer_id=peer_id, cmid=cmid, reaction_id=reaction_id
            )
        except Exception as e:
            logger.error(f"Не удалось поставить реакцию: {e}")

    async def get_chat_leaders(self, chat_id):
        """Возвращает список тегов всех лидеров в указанной беседе (с кешем)"""
        current_time = time.time()

        # Кеш для конкретной беседы на 5 минут
        if (current_time - self.leaders_cache_time < 300 and 
            self.leaders_cache and 
            self.leaders_cache_chat_id == chat_id):
            return self.leaders_cache

        try:
            # Получаем список участников беседы
            chat_info = self.vk.messages.getConversationMembers(peer_id=chat_id)
            leader_tags = []

            # Получаем всех лидеров из БД
            from users_db import get_all_leaders
            leaders = get_all_leaders()
            leader_ids = [leader[0] for leader in leaders]

            # Проходим по участникам беседы
            for member in chat_info.get("items", []):
                member_id = member.get("member_id")
                if member_id and member_id in leader_ids:
                    try:
                        user_info = self.vk.users.get(user_ids=member_id)[0]
                        screen_name = user_info.get("screen_name", "")
                        first_name = user_info.get("first_name", "")
                        last_name = user_info.get("last_name", "")

                        if screen_name:
                            tag = f"[id{member_id}|@{screen_name}]"
                        else:
                            full_name = f"{first_name} {last_name}".strip()
                            tag = f"[id{member_id}|{full_name or f'id{member_id}'}]"

                        leader_tags.append(tag)
                    except:
                        leader_tags.append(f"[id{member_id}|id{member_id}]")

            # Обновляем кеш
            self.leaders_cache = leader_tags
            self.leaders_cache_time = current_time
            self.leaders_cache_chat_id = chat_id

            return leader_tags

        except Exception as e:
            logger.error(f"Ошибка получения участников беседы: {e}")
            return self.leaders_cache  # возвращаем старый кеш при ошибке

    async def get_chat_name_cached(self, peer_id):
        """Получает название беседы с кэшированием на 1 час"""
        current_time = time.time()

        # Проверяем кэш
        if peer_id in self.chat_names_cache:
            cache_time = self.chat_names_cache_time.get(peer_id, 0)
            if current_time - cache_time < 3600:  # 1 час
                return self.chat_names_cache[peer_id]

        try:
            if peer_id >= 2000000000:
                conversation = self.vk.messages.getConversationsById(peer_ids=peer_id)

                if conversation and conversation.get('items'):
                    chat_info = conversation['items'][0]
                    chat_name = chat_info.get('chat_settings', {}).get('title', 'Без названия')

                    # Сохраняем в кэш
                    self.chat_names_cache[peer_id] = chat_name
                    self.chat_names_cache_time[peer_id] = current_time

                    return chat_name
            return "Личные сообщения"
        except Exception as e:
            logger.error(f"Ошибка получения названия беседы {peer_id}: {e}")
            return "❌ Ошибка"

    async def handle_register_chat(self, peer_id, user_id, text, user_display):
        """Регистрирует текущую беседу для определённой роли"""

        # Только админы могут регистрировать беседы
        if not check_admin(user_id):
            self.send_message(peer_id, "⛔ Только администраторы могут регистрировать беседы")
            return

        # Проверяем, что это беседа
        if peer_id < 2000000000:
            self.send_message(peer_id, "❌ Эта команда работает только в беседах")
            return

        role = None
        role_name = None

        if text.startswith("/regleader"):
            role = "leader"
            role_name = "Лидеров"
        elif text.startswith("/regcourt"):
            role = "judge"
            role_name = "Судей"
        elif text.startswith("/regatt"):
            role = "attorney"
            role_name = "Атторнеев"
        elif text.startswith("/regadmin"):
            role = "admin"
            role_name = "Администрации"
        elif text.startswith("/regmy"):
            role = "ministry_of_justice"
            role_name = "Министерства Юстиции"

        if role:
            from users_db import save_role_chat
            save_role_chat(role, peer_id, user_id)

            self.send_message(
                peer_id,
                f"✅ Эта беседа зарегистрирована как беседа {role_name}\n"
                f"Теперь при выходе участников из этой беседы у них будет автоматически сниматься роль {role_name}"
            )

            await self.logger.log_action(
                "register_role_chat",
                user_display,
                f"Беседа {peer_id}",
                f"Зарегистрирована как {role_name}",
                source_peer_id=peer_id,
            )

    def resolve_username(self, user_id):
        # 1. Пробуем взять из базы
        from users_db import get_username
        name = get_username(user_id)
        if name:
            return name

        # 2. Пробуем через VK API (строка!)
        try:
            info = self.vk.users.get(user_ids=str(user_id), fields="screen_name")[0]
            first = info.get("first_name", "")
            last = info.get("last_name", "")
            screen = info.get("screen_name", "")

            full = f"{first} {last}".strip()
            if screen:
                full += f" (@{screen})"

            if full.strip():
                return full

        except:
            pass

        # 3. Если VK не дал имя — делаем красивый fallback
        return f"[id{user_id}|Пользователь]"

    ROLE_EMOJI = {
        "admin": "👑 Админ",
        "judge": "⚖️ Судья",
        "attorney": "📘 Атторней",
        "leader": "🛡 Лидер"
    }

    async def handle_chat_leave(self, peer_id, user_id):
        from database import get_all_roles, remove_all_roles
        from users_db import get_role_chat, get_username

        # Получаем имя
        username = self.resolve_username(user_id)

        if not username:
            try:
                info = self.vk.users.get(user_ids=user_id, fields="screen_name")[0]
                first = info.get("first_name", "")
                last = info.get("last_name", "")
                screen = info.get("screen_name", "")
                username = f"{first} {last}".strip()
                if screen:
                    username += f" (@{screen})"
            except:
                username = f"id{user_id}"

        # Получаем роли
        roles = get_all_roles(user_id)
        pretty_roles = [ROLE_EMOJI.get(r, r) for r in roles] if roles else []

        if roles:
            self.send_message(
                peer_id,
                f"👋 {username} покинул чат.\n"
                f"🔰 Доступ к боту автоматически снят.\n"
                f"💡 При возвращении доступ потребуется восстановить через администратора.\n\n"
                f"Снятые роли: {', '.join(pretty_roles)}"
            )
        else:
            self.send_message(
                peer_id,
                f"👋 {username} покинул чат.\n"
                f"🔰 Доступ к боту отсутствует.\n"
                f"💡 При возвращении доступ потребуется восстановить через администратора."
            )

        # Теперь можно спокойно снимать роли
        if roles:
            remove_all_roles(user_id)

            await self.logger.log_action(
                "auto_role_remove",
                username,
                f"Беседа {peer_id}",
                f"Сняты роли: {', '.join(pretty_roles)}",
                source_peer_id=peer_id,
            )

    async def handle_group_leave(self, event):
        user_id = event.object.user_id
        peer_id = event.object.peer_id
        self_id = event.group_id

        logger.warning(f"GROUP_LEAVE пойман: user_id={user_id}, peer_id={peer_id}")

        # Игнорируем выход бота
        if user_id == self_id:
            return

        # Проверяем, действительно ли пользователь вышел
        try:
            members = self.vk.messages.getConversationMembers(peer_id=peer_id)
            ids = [m["member_id"] for m in members["items"]]
            if user_id in ids:
                logger.info(f"Ложное событие: пользователь {user_id} всё ещё в беседе")
                return
        except:
            pass

        # Получаем информацию о пользователе
        try:
            user_info = self.vk.users.get(user_ids=user_id)[0]
            user_display = f"{user_info['first_name']} {user_info['last_name']} (@{user_info.get('screen_name', str(user_id))})"
        except:
            user_display = f"id{user_id}"

        logger.info(f"👤 ПОКИНУЛ БЕСЕДУ: {user_display} | peer_id={peer_id}")

        # Проверяем, зарегистрирована ли эта беседа для какой-то роли
        from users_db import get_all_role_chats
        role_chats = get_all_role_chats()
        logger.info(f"Зарегистрированные беседы: {role_chats}")

        role_found = None
        for role, chat_id in role_chats.items():
            if peer_id == chat_id:
                logger.info(f"🔍 Найдена роль {role} для беседы {peer_id}")

                if role == 'leader':
                    await self.remove_leader_role(user_id, user_display, peer_id)
                elif role == 'judge':
                    await self.remove_judge_role(user_id, user_display, peer_id)
                elif role == 'attorney':
                    await self.remove_attorney_role(user_id, user_display, peer_id)
                elif role == 'admin':
                    await self.remove_admin_role(user_id, user_display, peer_id)
            else:
                logger.info(f"Неизвестная роль {role_found}")
        else:
            logger.info(f"Беседа {peer_id} не зарегистрирована для автоматического снятия ролей")

    async def remove_leader_role(self, user_id, user_display, chat_id=None):
        """Снимает роль лидера"""
        try:
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()

            # Проверяем, был ли пользователь лидером
            cursor.execute('SELECT is_leader FROM users WHERE vk_id = ?', (user_id,))
            result = cursor.fetchone()

            if result and result[0] == 1:
                cursor.execute('UPDATE users SET is_leader = 0 WHERE vk_id = ?', (user_id,))
                conn.commit()

                # Уведомляем в беседу
                if chat_id:
                    self.send_message(chat_id, f"❌ {user_display} покинул беседу → роль Лидера снята")

                logger.info(f"✅ Снята роль лидера: {user_display} (id{user_id})")

                await self.logger.log_action(
                    'auto_remove_leader',
                    'Система',
                    user_display,
                    'Пользователь покинул беседу лидеров',
                    source_peer_id=chat_id if chat_id else 0
                )
            else:
                logger.info(f"Пользователь {user_display} не был лидером")

            conn.close()

        except Exception as e:
            logger.error(f"Ошибка снятия роли лидера: {e}")

    async def remove_judge_role(self, user_id, user_display, chat_id=None):
        """Снимает роль судьи"""
        try:
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()

            # Проверяем, был ли пользователь лидером
            cursor.execute('SELECT is_judge FROM users WHERE vk_id = ?', (user_id,))
            result = cursor.fetchone()

            if result and result[0] == 1:
                cursor.execute('UPDATE users SET is_judge = 0 WHERE vk_id = ?', (user_id,))
                conn.commit()

                # Уведомляем в беседу
                if chat_id:
                    self.send_message(chat_id, f"❌ {user_display} покинул беседу → роль Судьи снята")

                logger.info(f"✅ Снята роль судьи: {user_display} (id{user_id})")

                await self.logger.log_action(
                    'auto_remove_leader',
                    'Система',
                    user_display,
                    'Пользователь покинул беседу судей',
                    source_peer_id=chat_id if chat_id else 0
                )
            else:
                logger.info(f"Пользователь {user_display} не был судьей")

            conn.close()

        except Exception as e:
            logger.error(f"Ошибка снятия роли судьи: {e}")

    async def remove_attorney_role(self, user_id, user_display, chat_id=None):
        """Снимает роль атторнея"""
        try:
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()

            # Проверяем, был ли пользователь лидером
            cursor.execute('SELECT is_attorney FROM users WHERE vk_id = ?', (user_id,))
            result = cursor.fetchone()

            if result and result[0] == 1:
                cursor.execute('UPDATE users SET is_attorney = 0 WHERE vk_id = ?', (user_id,))
                conn.commit()

                # Уведомляем в беседу
                if chat_id:
                    self.send_message(chat_id, f"❌ {user_display} покинул беседу → роль Атторнея снята")

                logger.info(f"✅ Снята роль атторнея: {user_display} (id{user_id})")

                await self.logger.log_action(
                    'auto_remove_leader',
                    'Система',
                    user_display,
                    'Пользователь покинул беседу атторнеев',
                    source_peer_id=chat_id if chat_id else 0
                )
            else:
                logger.info(f"Пользователь {user_display} не был атторнеем")

            conn.close()

        except Exception as e:
            logger.error(f"Ошибка снятия роли атторнея: {e}")

    async def remove_admin_role(self, user_id, user_display, chat_id=None):
        """Снимает роль админа"""
        try:
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()

            # Проверяем, был ли пользователь лидером
            cursor.execute('SELECT is_admin FROM users WHERE vk_id = ?', (user_id,))
            result = cursor.fetchone()

            if result and result[0] == 1:
                cursor.execute('UPDATE users SET is_admin = 0 WHERE vk_id = ?', (user_id,))
                conn.commit()

                # Уведомляем в беседу
                if chat_id:
                    self.send_message(chat_id, f"❌ {user_display} покинул беседу → роль Админа снята")

                logger.info(f"✅ Снята роль админа: {user_display} (id{user_id})")

                await self.logger.log_action(
                    'auto_remove_leader',
                    'Система',
                    user_display,
                    'Пользователь покинул беседу админов',
                    source_peer_id=chat_id if chat_id else 0
                )
            else:
                logger.info(f"Пользователь {user_display} не был админом")

            conn.close()

        except Exception as e:
            logger.error(f"Ошибка снятия роли админа: {e}")

    # ================= ФОРУМ: ДОСТУП И ИНФО =================

    def extract_thread_id_from_url(self, text):
        if text.isdigit():
            return int(text)
        m = re.search(r"threads/[^\.]+\.(\d+)", text)
        if m:
            return int(m.group(1))
        m = re.search(r"/(\d+)/?$", text)
        if m:
            return int(m.group(1))
        return None

    async def is_thread_allowed(self, thread_id, user_id, user_is_admin=False):
        if user_is_admin:
            return True, "", "allowed"

        try:
            thread = await self.forum_api.get_thread(thread_id)
            if thread is None:
                return False, "❌ Тема не найдена или нет доступа", "not_found"

            category = await thread.get_category()
            if not category:
                return False, "❌ Не удалось определить раздел темы.", "error"

            # 1. ЛИДЕРЫ (должны проверяться ПЕРЕД судьями)
            if is_leader(user_id):
                from config import LEADER_ALLOWED_FORUMS

                if category.id in LEADER_ALLOWED_FORUMS:
                    return True, "", "allowed"
                else:
                    return (
                        False,
                        "⛔ Лидеры могут работать только в разрешённых разделах.",
                        "forbidden",
                    )

            # 2. АТТОРНЕИ
            if is_attorney(user_id):
                if category.id == 3287:
                    return True, "", "allowed"
                else:
                    return (
                        False,
                        "⛔ Атторнеи могут работать только в разделе Атторнейских дел.",
                        "forbidden",
                    )

            # 3. СУДЬИ
            if is_user_allowed(user_id):
                if category.id == 3423:
                    return True, "", "allowed"
                else:
                    return (
                        False,
                        "⛔ Судьи могут работать только в разделе Судебных исков.",
                        "forbidden",
                    )

            # 4. Остальные
            return False, "⛔ У вас нет прав для работы с ботом.", "forbidden"

        except Exception as e:
            logger.error(f"Ошибка проверки доступа к теме {thread_id}: {e}")
            return False, "❌ Ошибка при проверке доступа.", "error"

    def create_action_keyboard(self, thread_id, user_id):
        """Создает клавиатуру с 2 базовыми кнопками для всех пользователей"""
        keyboard = VkKeyboard(inline=True)
        created_at = int(time.time())

        # Кнопка закрыть/открыть
        keyboard.add_button(
            "🔒 Закрыть / 🔓 Открыть",
            color=VkKeyboardColor.PRIMARY,
            payload={
                "cmd": "toggle_open_close",
                "thread_id": thread_id,
                "creator_id": user_id,
                "created_at": created_at,
            },
        )

        # Кнопки закрепить/открепить
        keyboard.add_line()
        keyboard.add_button(
            "📌 Закрепить",
            color=VkKeyboardColor.PRIMARY,
            payload={
                "cmd": "pin",
                "thread_id": thread_id,
                "creator_id": user_id,
                "created_at": created_at,
            },
        )
        keyboard.add_button(
            "📌 Открепить",
            color=VkKeyboardColor.PRIMARY,
            payload={
                "cmd": "unpin",
                "thread_id": thread_id,
                "creator_id": user_id,
                "created_at": created_at,
            },
        )

        return keyboard

    def create_admin_keyboard(self, thread_id, user_id):
        """Создает полную клавиатуру для администраторов"""
        keyboard = VkKeyboard(inline=True)
        created_at = int(time.time())

        # Базовые кнопки
        keyboard.add_button(
            "🔒 Закрыть / 🔓 Открыть",
            color=VkKeyboardColor.PRIMARY,
            payload={
                "cmd": "toggle_open_close",
                "thread_id": thread_id,
                "creator_id": user_id,
                "created_at": created_at,
            },
        )

        # Кнопки закрепить/открепить
        keyboard.add_line()
        keyboard.add_button(
            "📌 Закрепить",
            color=VkKeyboardColor.PRIMARY,
            payload={
                "cmd": "pin",
                "thread_id": thread_id,
                "creator_id": user_id,
                "created_at": created_at,
            },
        )
        keyboard.add_button(
            "📌 Открепить",
            color=VkKeyboardColor.PRIMARY,
            payload={
                "cmd": "unpin",
                "thread_id": thread_id,
                "creator_id": user_id,
                "created_at": created_at,
            },
        )

        # Админские кнопки
        keyboard.add_line()

        keyboard.add_button(
            "✏️ Изменить название",
            color=VkKeyboardColor.PRIMARY,
            payload={
                "cmd": "edit_title",
                "thread_id": thread_id,
                "creator_id": user_id,
                "created_at": created_at,
            },
        )

        keyboard.add_button(
            "🗑️ Удалить тему",
            color=VkKeyboardColor.PRIMARY,
            payload={
                "cmd": "delete_thread",
                "thread_id": thread_id,
                "creator_id": user_id,
                "created_at": created_at,
            },
        )

        keyboard.add_line()

        keyboard.add_button(
            "🔄 Обновить инфо",
            color=VkKeyboardColor.PRIMARY,
            payload={
                "cmd": "refresh_info",
                "thread_id": thread_id,
                "creator_id": user_id,
                "created_at": created_at,
            },
        )

        keyboard.add_button(
            "📦 Перенести тему",
            color=VkKeyboardColor.PRIMARY,
            payload={
                "cmd": "move_thread",
                "thread_id": thread_id,
                "creator_id": user_id,
                "created_at": created_at,
            },
        )

        return keyboard

    async def show_help(self, peer_id):
        help_text = (
            "╔════════════════════╗\n"
            "║   🤖 Команды бота   ║\n"
            "╚════════════════════╝\n\n"
            "📋 Основные команды\n"
            "▸ !info [ссылка] — информация о теме\n"
            "▸ !edit [ссылка] — действия с темой\n"
            "▸ !help — показать это сообщение\n"
            "▸ !getid — ID текущего чата\n\n"
            "⚖️ Команды для судей\n"
            "▸ /notif Ник Текст — отправить повестку\n"
            "▸ !notif status — статус ваших повесток\n"
            "▸ !notif all — все повестки (для админов)\n\n"
            "👑 Админ-команды\n"
            "▸ !addcourt @user [заметка] — добавить судью\n"
            "▸ !deluser @user — удалить пользователя\n"
            "▸ !court — список судей\n"
            "▸ !addatt @user [заметка] — добавить атторнея\n"
            "▸ !attorney — список атторнеев\n"
            "▸ !addadmin @user [заметка] — сделать админом\n"
            "▸ !admins — список админов\n"
            "▸ !setpost @user Новая должность — сменить должность\n"
            "▸ !иски [страниц] — статистика по закрытым темам\n"
            "▸ !reboot — перезапустить бота\n"
            "▸ !delnotif [ID] — удалить повестку\n"
            "▸ !notif all — все повестки (для админов)\n\n"
            "📌 Регистрация бесед\n"
            "▸ /regleader — зарегистрировать беседу лидеров\n"
            "▸ /regcourt — зарегистрировать беседу судей\n"
            "▸ /regatt — зарегистрировать беседу атторнеев\n"
            "▸ /regadmin — зарегистрировать беседу админов\n"
            "▸ /regmy — зарегистрировать беседу МЮ\n"
            "▸ !chats — список зарегистрированных бесед\n"
            "▸ !delchat [роль] — удалить зарегистрированную беседу\n\n"
        )
        self.send_message(peer_id, help_text)

    async def show_thread_info(
        self, peer_id, user_id, thread_id, user_display, show_keyboard=False
    ):
        """Показывает информацию о теме (без кнопок или с кнопками только для админов)"""
        try:
            user_is_admin = check_admin(user_id)
            is_allowed, error_message, access_status = await self.is_thread_allowed(
                thread_id, user_id, user_is_admin
            )

            if not is_allowed:
                if access_status == "not_found":
                    error_msg = (
                        f"❌ Тема {thread_id} не найдена или нет прав на просмотр."
                    )
                else:
                    error_msg = error_message
                self.send_message(peer_id, error_msg)
                await self.logger.log_action(
                    "thread_info_error",
                    user_display,
                    f"Тема {thread_id}",
                    f"{access_status}: {error_message}",
                    source_peer_id=peer_id,
                )
                return

            thread = await self.forum_api.get_thread(thread_id)
            if thread is None:
                self.send_message(peer_id, f"❌ Тема {thread_id} не найдена")
                return

            is_closed = getattr(thread, "is_closed", False)
            is_pinned = (
                getattr(thread, "is_sticky", False)
                if hasattr(thread, "is_sticky")
                else False
            )

            author_name = "Неизвестно"
            author_id = None
            if getattr(thread, "creator", None):
                creator = thread.creator
                if getattr(creator, "username", None):
                    author_name = creator.username
                    author_id = getattr(creator, "id", None)

            created_date = "Неизвестно"
            if getattr(thread, "create_date", None):
                try:
                    created_date = datetime.fromtimestamp(thread.create_date).strftime(
                        "%Y-%m-%d"
                    )
                except:
                    created_date = str(thread.create_date)

            forum_name = "Неизвестно"
            try:
                category = await thread.get_category()
                if category and getattr(category, "title", None):
                    forum_name = category.title
            except:
                pass

            status_emoji = "🔒" if is_closed else "🔓"
            pin_emoji = "📌" if is_pinned else "📍"
            status_text = "Закрыта" if is_closed else "Открыта"

            info = (
                f"{status_emoji} Тема: {thread.title} {pin_emoji}\n"
                f"━━━━━━━━━━━━━━━━\n"
                f"🆔 ID: {thread_id}\n"
                f"{status_emoji} Статус: {status_text}\n"
                f"👤 Автор: {author_name}"
                + (f" (id{author_id})" if author_id else "")
                + "\n"
                f"📅 Создана: {created_date}\n"
                f"📂 Раздел: {forum_name}\n"
                f"━━━━━━━━━━━━━━━━\n"
            )

            # Кнопки только для админов, если show_keyboard=True
            if show_keyboard and user_is_admin:
                info += "👇 Выбери действие:"
                keyboard = self.create_admin_keyboard(thread_id, user_id)
                self.send_message(peer_id, info, keyboard)
            else:
                self.send_message(peer_id, info)

            await self.logger.log_action(
                "thread_info",
                user_display,
                f"Тема {thread_id}: {thread.title[:50]}...",
                "Успешно",
                source_peer_id=peer_id,
            )

        except Exception as e:
            logger.error(f"Ошибка в show_thread_info: {traceback.format_exc()}")
            self.send_message(
                peer_id, f"⚠️ Не удалось получить информацию: {str(e)[:100]}"
            )
            await self.logger.log_action(
                "thread_info",
                user_display,
                f"Тема {thread_id}",
                f"Ошибка: {str(e)[:50]}",
                source_peer_id=peer_id,
            )

    # ================= CALLBACK-КНОПКИ =================

    async def _perform_reboot(self):
        try:
            await asyncio.sleep(1)
            logger.info("=" * 50)
            logger.info("ПЕРЕЗАПУСК БОТА ПО КОМАНДЕ")
            logger.info("=" * 50)
            import sys, os

            try:
                await self.forum_api.close()
            except:
                pass
            os.execv(sys.executable, ["python"] + sys.argv)
        except Exception as e:
            logger.error(f"Ошибка при перезапуске: {e}")
            import sys

            sys.exit(0)

    async def _handle_resolution_callback(
        self, peer_id, user_id, payload, user_display, conversation_message_id=None
    ):
        cmd = payload["cmd"]
        form_name = payload["form_name"]
        notification_id = payload.get("notification_id")  # Добавляем ID уведомления

        # Проверка роли
        if not is_leader(user_id):
            self.send_message(
                peer_id, "⛔ Только лидеры могут принимать постановления."
            )
            return

        if cmd == "accept_resolution":
            result = "ПРИНЯТО"
            emoji = "✅"
        else:
            result = "ОТКЛОНЕНО"
            emoji = "❌"

        # Редактируем исходное сообщение с постановлением, убирая кнопки
        if conversation_message_id:
            try:
                # Получаем текущее сообщение
                msg_data = self.vk.messages.getByConversationMessageId(
                    peer_id=peer_id, conversation_message_ids=[conversation_message_id]
                )
                if msg_data and msg_data.get("items"):
                    current_text = msg_data["items"][0].get("text", "")
                    # Обновляем сообщение, добавляя статус и убирая кнопки
                    new_text = f"{current_text}\n\n{emoji} Статус: {result}\n✅ Принял: {user_display}"
                    await self.safe_edit(
                        peer_id,
                        cmid=conversation_message_id,
                        new_text=new_text,
                        remove_keyboard=True,
                    )
            except Exception as e:
                logger.error(f"Ошибка редактирования сообщения с постановлением: {e}")

        # Отправляем уведомление в тот же чат (можно без дублирования)
        self.send_message(
            peer_id, f"{emoji} Постановление: {result} (обработал: {user_display})"
        )

        judge_peer_id = payload.get("judge_peer_id")
        judge_display = payload.get("judge_display")

        if judge_peer_id:
            # Отправляем уведомление обратно судье
            judge_notify = (
                f"{emoji} Ваше постановление «{form_name}» {result.lower()}\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"✅ Обработал: {user_display}\n"
                f"📅 Время: {datetime.now().strftime('%d.%m.%Y %H:%M')}"
            )
            try:
                self.send_message(judge_peer_id, judge_notify)
            except Exception as e:
                logger.error(
                    f"Не удалось отправить уведомление судье {judge_peer_id}: {e}"
                )

        await self.logger.log_action(
            "resolution_action", user_display, form_name, result, source_peer_id=peer_id
        )

    async def _send_resolution_to_my(self, peer_id, user_id, user_display, form_name, fields, values, thread_id=None, thread_title=None):
        """Отправляет постановление в МЮ с ссылкой на дело"""

        # Получаем ID беседы МЮ из БД
        from users_db import get_role_chat
        mj_chat_id = get_role_chat('ministry_of_justice')

        if not mj_chat_id:
            self.send_message(peer_id, "❌ Беседа МЮ не зарегистрирована. Используйте /regmy")
            return

        # Формируем текст постановления
        text = f"📄 {form_name}\n━━━━━━━━━━━━━━\n"

        # Добавляем информацию о деле, если есть
        if thread_id:
            thread_url = f"https://forum.arizona-rp.com/threads/{thread_id}/"
            text += f"🔗 Дело: ({thread_url})\n"
            text += f"🆔 Название темы: {thread_title}\n"
            text += "━━━━━━━━━━━━━━\n"

        for f, v in zip(fields, values):
            text += f"• {f}: {v}\n"
        text += "━━━━━━━━━━━━━━\n"
        text += f"👨‍⚖️ Судья: {user_display}\n"
        text += f"🕐 Время: {datetime.now().strftime('%d.%m.%Y %H:%M')}"

        # Получаем всех лидеров в беседе МЮ
        leaders = await self.get_chat_leaders(mj_chat_id)

        # Формируем текст с тегами
        if leaders:
            mention_text = " ".join(leaders) + "\n\n"
            full_text = mention_text + text
        else:
            full_text = text

        kb = VkKeyboard(inline=True)

        import time
        notification_id = int(time.time())

        kb.add_button(
            "✅ Принять",
            color=VkKeyboardColor.POSITIVE,
            payload={
                "cmd": "accept_resolution",
                "form_name": form_name,
                "notification_id": notification_id,
                "judge_peer_id": peer_id,
                "judge_display": user_display,
                "thread_id": thread_id,
            },
        )
        kb.add_button(
            "❌ Отклонить",
            color=VkKeyboardColor.NEGATIVE,
            payload={
                "cmd": "reject_resolution",
                "form_name": form_name,
                "notification_id": notification_id,
                "judge_peer_id": peer_id,
                "judge_display": user_display,
                "thread_id": thread_id,
            },
        )

        # Отправляем в МЮ
        self.send_message(mj_chat_id, full_text, kb)

        # Отправляем подтверждение судье
        self.send_message(
            peer_id,
            f"✅ Постановление по делу #{thread_id if thread_id else '?'} отправлено в МЮ на рассмотрение.\nУведомлены: {len(leaders)} лидер(ов)"
        )

        await self.logger.log_action(
            "resolution_sent",
            user_display,
            form_name,
            f"Дело #{thread_id} отправлено в МЮ",
            source_peer_id=peer_id,
        )

    async def handle_resolution_form_step(self, user_id, text):
        data = self.user_data[user_id]

        # Проверка на отмену
        if text.lower() in ["отмена", "cancel", "-"]:
            self.send_message(data["peer_id"], "❌ Заполнение постановления отменено")
            del self.user_data[user_id]
            return

        fields = data["fields"]
        values = data["values"]
        peer_id = data["peer_id"]

        # Проверка на пустое поле
        if not text.strip():
            next_field = fields[len(values)]
            self.send_message(
                peer_id, f"❌ Поле не может быть пустым.\nВведите {next_field}:"
            )
            return

        values.append(text.strip())

        if len(values) == len(fields):
            await self._send_resolution_to_my(
                peer_id,
                user_id,
                data.get("user_display", "Неизвестно"),
                data["form_name"],
                fields,
                values,
                data.get("thread_id"),
                data.get("thread_title"),
            )
            del self.user_data[user_id]
            return

        next_field = fields[len(values)]
        field_num = len(values) + 1
        self.send_message(
            peer_id,
            f"📝 Поле {field_num}/{len(fields)}\n**{next_field}**\n\n💬 Введите значение:",
        )

    async def handle_resolution_command(self, peer_id, user_id, text, user_display):
        """Обработка команд постановлений с ссылкой на дело"""

        if not (is_user_allowed(user_id) or is_attorney(user_id)):
            self.send_message(
                peer_id, "⛔ Только судьи и прокуроры могут выдавать постановления."
            )
            return

        parts = text.split(" ", 3)  # Разбиваем на 4 части: /res, тип, ссылка, данные
        if len(parts) < 3:
            help_text = (
                "📋 Формат команды /res\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                "/res <тип> <ссылка на дело> [данные]\n\n"
                "Типы постановлений:\n"
                "• доква — Об истребовании доказательств\n"
                "• дело — О решении по делу\n"
                "• личность — Об установке личности\n\n"
                "Примеры:\n"
                "▸ Короткая форма (через |):\n"
                "/res доква https://forum.arizona-rp.com/threads/число/ A.Starikov|Кто снял розыск?|ФБР|24 часа\n\n"
                "▸ Без данных (заполните вручную):\n"
                "/res дело https://forum.arizona-rp.com/threads/число/\n\n"
                "⚠️ Ссылка на дело обязательна!"
            )
            self.send_message(peer_id, help_text)
            return

        rtype = parts[1].lower()
        thread_url = parts[2].strip()
        short_data = parts[3] if len(parts) > 3 else None

        # Проверяем ссылку
        thread_id = self.extract_thread_id_from_url(thread_url)
        if not thread_id:
            self.send_message(
                peer_id,
                "❌ Неверный формат ссылки.\n✅ Правильный формат: `https://forum.arizona-rp.com/threads/число/`",
            )
            return

        # Проверяем, существует ли тема и есть ли к ней доступ
        try:
            thread = await self.forum_api.get_thread(thread_id)
            if not thread:
                self.send_message(
                    peer_id, f"❌ Тема с ID {thread_id} не найдена или нет доступа"
                )
                return
            thread_title = getattr(thread, "title", "Без названия")
        except Exception as e:
            logger.error(f"Ошибка проверки темы: {e}")
            self.send_message(peer_id, "❌ Не удалось проверить ссылку на тему")
            return

        # Определяем форму
        if rtype == "доква":
            form_name = "Постановление «Об истребовании доказательств»"
            fields = [
                "Ник судьи",
                "Что истребовано",
                "У кого истребовано",
                "Срок исполнения",
            ]
        elif rtype == "дело":
            form_name = "Постановление «О решении по делу»"
            fields = ["Ник судьи", "Что сделать", "Кому выполнить", "Срок исполнения"]
        elif rtype == "личность":
            form_name = "Судебный запрос «Об установке личности»"
            fields = ["Ник судьи", "Дело", "Орган исполнения", "Срок исполнения"]
        else:
            self.send_message(
                peer_id,
                "❗ Неизвестный тип постановления.\nДоступные типы: `доква`, `дело`, `личность`",
            )
            return

        # Если короткая форма
        if short_data:
            values = short_data.split(" ")
            if len(values) != len(fields):
                self.send_message(
                    peer_id,
                    f"❗ Короткая форма должна содержать {len(fields)} полей через пробел\n"
                    f"Пример: {fields[0]} {fields[1]} {fields[2]} {fields[3]}",
                )
                return

            await self._send_resolution_to_my(
                peer_id,
                user_id,
                user_display,
                form_name,
                fields,
                values,
                thread_id,
                thread_title,
            )
            return

        field_examples = {
            "Ник судьи": "A.Starikov",
            "Что истребовано": "Логи действий",
            "У кого истребовано": "ФБР",
            "Срок исполнения": "24 часа",
            "Что сделать": "Уволить сотрудника",
            "Кому выполнить": "МВД",
            "Дело": "#12345",
            "Орган исполнения": "Полиция"
        }

        fields_info = []
        for i, field in enumerate(fields, 1):
            example = field_examples.get(field, "пример")
            fields_info.append(f"{i}. {field}\n   💡 Пример: {example}")

        hint = (
            f"📝 {form_name}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🔗 Дело: [{thread_title}]({thread_url})\n"
            f"🆔 ID темы: {thread_id}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Заполните поля:\n\n"
            f"{chr(10).join(fields_info)}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💬 Вводите поля по очереди.\n"
            f"❌ Для отмены напишите `отмена`"
        )

        self.user_data[user_id] = {
            "action": "awaiting_resolution_form",
            "form_name": form_name,
            "fields": fields,
            "values": [],
            "peer_id": peer_id,
            "thread_id": thread_id,
            "thread_url": thread_url,
            "thread_title": thread_title,
        }

        kb = VkKeyboard(inline=True)
        kb.add_button(
            "❌ Отмена",
            color=VkKeyboardColor.NEGATIVE,
            payload={"cmd": "cancel_resolution_form"},
        )

        self.send_message(peer_id, hint, kb)

    async def update_thread_state(self, thread_id, **kwargs):
        """Обновляет тему, сохраняя все остальные параметры"""
        thread = await self.forum_api.get_thread(thread_id)
        if not thread:
            return None

        # Получаем текущие значения
        current_title = getattr(thread, "title", "")
        current_is_closed = getattr(thread, "is_closed", False)
        current_is_sticky = getattr(thread, "is_sticky", False)

        # Формируем параметры для обновления
        update_params = {
            "title": kwargs.get("title", current_title),
            "opened": kwargs.get("opened", not current_is_closed),
            "sticky": kwargs.get("sticky", current_is_sticky),
        }

        return await thread.edit_info(**update_params)

    async def handle_callback(self, peer_id, user_id, payload, user_display):
        cmd = payload.get("cmd")
        conversation_message_id = payload.get("conversation_message_id")

        if cmd in ["accept_resolution", "reject_resolution"]:
            await self._handle_resolution_callback(
                peer_id, user_id, payload, user_display, conversation_message_id
            )
            return

        # Перезапуск
        if cmd == "confirm_reboot":
            user_id_from_payload = payload.get("user_id")
            if user_id != user_id_from_payload:
                self.send_message(peer_id, "⛔ Это не ваша команда")
                return
            if not check_admin(user_id):
                self.send_message(
                    peer_id, "⛔ Только администраторы могут перезапускать бота"
                )
                return

            await self.safe_edit(
                peer_id,
                cmid=conversation_message_id,
                new_text="🔄 Перезапуск бота...",
                remove_keyboard=True,
            )

            await self.logger.log_action(
                "bot_reboot",
                user_display,
                "Бот",
                "Перезапуск по команде",
                source_peer_id=peer_id,
            )
            asyncio.create_task(self._perform_reboot())
            return

        if cmd == "cancel_reboot":
            await self.safe_edit(
                peer_id,
                cmid=conversation_message_id,
                new_text="❌ Перезапуск отменен",
                remove_keyboard=True,
            )
            return

        if cmd == "cancel_resolution_form":
            if (
                user_id in self.user_data
                and self.user_data[user_id].get("action") == "awaiting_resolution_form"
            ):
                del self.user_data[user_id]
                self.send_message(peer_id, "❌ Заполнение постановления отменено")
                # Убираем клавиатуру у сообщения
                if conversation_message_id:
                    await self.safe_edit(
                        peer_id,
                        cmid=conversation_message_id,
                        new_text="❌ Отменено",
                        remove_keyboard=True,
                    )
            return

        # Повестки
        if cmd in [
            "accept_notify",
            "reject_notify",
            "confirm_delete_all",
            "cancel_action",
        ]:
            await self.handle_notify_callback(peer_id, user_id, payload, user_display)
            # после обработки убираем клавиатуру
            if conversation_message_id:
                try:
                    msg_data = self.vk.messages.getByConversationMessageId(
                        peer_id=peer_id,
                        conversation_message_ids=[conversation_message_id],
                    )
                    if msg_data and msg_data.get("items"):
                        current_text = msg_data["items"][0].get("text", "")
                        await self.safe_edit(
                            peer_id,
                            cmid=conversation_message_id,
                            new_text=current_text,
                            remove_keyboard=True,
                        )
                except Exception as e:
                    logger.error(f"Ошибка при удалении клавиатуры: {e}")
            return

        # Кнопки форума
        thread_id = payload.get("thread_id")
        creator_id = payload.get("creator_id")
        created_at = payload.get("created_at", 0)

        if not thread_id:
            self.send_message(peer_id, "❌ Ошибка: ID темы не найден")
            return

        user_is_admin = check_admin(user_id)
        current_time = int(time.time())

        # Для админов убираем ограничение по времени и по создателю
        if not user_is_admin:
            if created_at and current_time - created_at > 300:
                self.send_message(
                    peer_id, "⏰ Время действия кнопок истекло. Используй !edit заново."
                )
                return

            if user_id != creator_id:
                self.send_message(
                    peer_id,
                    "⛔ Эти кнопки вызваны другим пользователем. Используй !edit.",
                )
                await self.logger.log_action(
                    "unauthorized_button_press",
                    user_display,
                    f"Тема {thread_id}, команда {cmd}",
                    f"Попытка нажать чужие кнопки (владелец: {creator_id})",
                    source_peer_id=peer_id,
                )
                return

        is_allowed, error_message, access_status = await self.is_thread_allowed(
            thread_id, user_id, user_is_admin
        )
        if not is_allowed:
            if access_status == "not_found":
                self.send_message(peer_id, f"❌ Тема {thread_id} не найдена")
            else:
                self.send_message(peer_id, error_message)
            await self.logger.log_action(
                "access_denied",
                user_display,
                f"Тема {thread_id}",
                f"{access_status}: {error_message}",
                source_peer_id=peer_id,
            )
            return

        try:
            action = None
            result_msg = "Успешно"
            success = False

            thread = await self.forum_api.get_thread(thread_id)
            if not thread:
                self.send_message(peer_id, f"❌ Тема {thread_id} не найдена")
                return

            # Автоматическое открытие / закрытие
            if cmd == "toggle_open_close":
                # Загружаем актуальное состояние
                thread = await self.forum_api.get_thread(thread_id)
                is_closed = thread.is_closed
                current_title = getattr(thread, "title", "")
                current_is_sticky = getattr(thread, "is_sticky", False)

                # Меняем состояние
                if is_closed:
                    # Тема закрыта → открываем
                    resp = await thread.edit_info(
                        opened=True, sticky=current_is_sticky, title=current_title
                    )
                    result_msg = "открыта"
                    emoji = "🔓"
                else:
                    # Тема открыта → закрываем
                    resp = await thread.edit_info(
                        opened=False, sticky=current_is_sticky, title=current_title
                    )
                    result_msg = "закрыта"
                    emoji = "🔒"

                if not resp or resp.status != 200:
                    self.send_message(peer_id, "⚠️ Ошибка при изменении статуса темы")
                    return

                self.send_message(peer_id, f"{emoji} Тема {thread_id} {result_msg}")

                await self.logger.log_action(
                    "toggle_open_close",
                    user_display,
                    f"Тема {thread_id}",
                    result_msg,
                    source_peer_id=peer_id,
                )
                return

            elif cmd == "pin":
                thread = await self.forum_api.get_thread(thread_id)
                current_title = getattr(thread, "title", "")
                is_closed = getattr(thread, "is_closed", False)
                resp = await thread.edit_info(
                    sticky=True, opened=not is_closed, title=current_title
                )
                action = "pin_thread"
                success = resp and resp.status == 200
                result_msg = "Закреплена" if success else "Ошибка"

            elif cmd == "unpin":
                thread = await self.forum_api.get_thread(thread_id)
                current_title = getattr(thread, "title", "")
                is_closed = getattr(thread, "is_closed", False)
                resp = await thread.edit_info(
                    sticky=False, opened=not is_closed, title=current_title
                )
                action = "unpin_thread"
                success = resp and resp.status == 200
                result_msg = "Откреплена" if success else "Ошибка"

            elif cmd == "edit_title":
                if not check_admin(user_id):
                    self.send_message(
                        peer_id, "⛔ Только администраторы могут изменять название темы"
                    )
                    await self.logger.log_action(
                        "unauthorized_edit_attempt",
                        user_display,
                        f"Тема {thread_id}",
                        "Попытка изменить название без прав админа",
                        source_peer_id=peer_id,
                    )
                    return

                # Получаем текущее название для подсказки
                thread = await self.forum_api.get_thread(thread_id)
                current_title = getattr(thread, "title", "")

                self.send_message(
                    peer_id,
                    f"📝 Текущее название: {current_title}\n\nВведите новое название для темы {thread_id}:",
                )
                self.user_data[user_id] = {
                    "action": "awaiting_new_title",
                    "thread_id": thread_id,
                    "creator_id": creator_id,
                    "created_at": created_at,
                    "current_title": current_title,  # Сохраняем текущее название на случай отмены
                }
                return

            elif cmd == "refresh_info":
                # При обновлении инфо показываем с кнопками только для админов
                user_is_admin = check_admin(user_id)
                if user_is_admin:
                    await self.show_thread_info(
                        peer_id, user_id, thread_id, user_display, show_keyboard=True
                    )
                else:
                    await self.show_thread_info(
                        peer_id, user_id, thread_id, user_display, show_keyboard=False
                    )
                return

            elif cmd == "delete_thread":
                if not check_admin(user_id):
                    self.send_message(
                        peer_id, "⛔ Только администраторы могут удалять темы"
                    )
                    return

                kb = VkKeyboard(inline=True)
                kb.add_button(
                    "✅ Да, удалить",
                    color=VkKeyboardColor.NEGATIVE,
                    payload={
                        "cmd": "confirm_delete",
                        "thread_id": thread_id,
                        "creator_id": creator_id,
                    },
                )
                kb.add_button(
                    "❌ Отмена",
                    color=VkKeyboardColor.POSITIVE,
                    payload={"cmd": "cancel_delete", "thread_id": thread_id},
                )
                self.send_message(
                    peer_id,
                    f"⚠️ Тема {thread_id} будет удалена без возможности восстановления!\n"
                    f"Укажите причину удаления одним сообщением:",
                    kb,
                )
                self.user_data[user_id] = {
                    "action": "awaiting_delete_reason",
                    "thread_id": thread_id,
                }
                return

            elif cmd == "cancel_delete":
                self.send_message(peer_id, "❌ Удаление отменено")
                return

            if success and cmd in ["toggle_close", "toggle_open", "pin", "unpin"]:
                try:
                    thread = await self.forum_api.get_thread(thread_id)
                    if thread:
                        is_closed = getattr(thread, "is_closed", False)
                        status_emoji = "🔒" if is_closed else "🔓"
                        if cmd in ["pin", "unpin"]:
                            status_text = "закреплена" if cmd == "pin" else "откреплена"
                        else:
                            status_text = "закрыта" if is_closed else "открыта"
                        self.send_message(
                            peer_id, f"{status_emoji} Тема {thread_id} {status_text}"
                        )
                except:
                    self.send_message(
                        peer_id, f"✅ Тема {thread_id} {result_msg.lower()}"
                    )

            if action:
                await self.logger.log_action(
                    action,
                    user_display,
                    f"Тема {thread_id}",
                    result_msg,
                    source_peer_id=peer_id,
                )

        except Exception as e:
            logger.error(f"Ошибка в callback: {traceback.format_exc()}")
            self.send_message(peer_id, f"⚠️ Ошибка: {str(e)[:100]}")
            await self.logger.log_action(
                cmd,
                user_display,
                f"Тема {thread_id}",
                f"Ошибка: {str(e)[:50]}",
                source_peer_id=peer_id,
            )

    async def get_court_stats(self, peer_id, user_display, pages=5):
        """Собирает статистику по закрытым темам из раздела судебных исков (ID 3419)"""
        try:
            from datetime import datetime, timedelta
            import time

            # Сразу отправляем первое сообщение, что начали
            self.send_message(
                peer_id, "⚙️ Загрузка статистики судебных исков | Love..."
            )

            category_id = 3423
            logger.info(
                f"=== БЫСТРЫЙ СБОР СТАТИСТИКИ: раздел {category_id}, страниц: {pages} ==="
            )

            # Получаем объект категории
            category = await self.forum_api.get_category(category_id)
            if not category:
                self.send_message(peer_id, f"❌ Раздел судебных исков не найден")
                return

            category_title = getattr(category, "title", "Судебные иски")

            # Собираем все ID тем сразу, без промежуточных сообщений
            all_thread_ids = []

            for page in range(1, pages + 1):
                try:
                    threads_dict = await category.get_threads(page=page)
                    if not threads_dict:
                        break

                    # Добавляем ТОЛЬКО обычные темы (unpins)
                    if "unpins" in threads_dict and threads_dict["unpins"]:
                        all_thread_ids.extend(threads_dict["unpins"])

                    # Закрепленные темы (pins) ПОЛНОСТЬЮ ИГНОРИРУЕМ, не добавляем в список

                    # БЕЗ ЗАДЕРЖЕК

                except Exception as e:
                    logger.error(f"Ошибка на странице {page}: {e}")
                    break

            total_threads = len(all_thread_ids)
            if total_threads == 0:
                self.send_message(peer_id, "❌ В разделе нет тем")
                return

            # Анализируем темы максимально быстро
            closed_by_stats = {}
            closed_count = 0
            open_count = 0

            for thread_id in all_thread_ids:
                try:
                    thread = await self.forum_api.get_thread(thread_id)
                    if not thread:
                        continue

                    if thread.is_closed:
                        closed_count += 1

                        # Быстро получаем автора последнего поста
                        closer_name = "Неизвестно"
                        try:
                            post_ids = await thread.get_posts()
                            if post_ids and len(post_ids) > 0:
                                last_post_id = post_ids[-1]
                                last_post = await self.forum_api.get_post(last_post_id)

                                if hasattr(last_post, "creator") and last_post.creator:
                                    creator = last_post.creator
                                    if (
                                        hasattr(creator, "username")
                                        and creator.username
                                    ):
                                        closer_name = creator.username
                        except:
                            pass

                        closed_by_stats[closer_name] = (
                            closed_by_stats.get(closer_name, 0) + 1
                        )
                    else:
                        open_count += 1

                    # БЕЗ ЗАДЕРЖЕК И ПРОМЕЖУТОЧНЫХ СООБЩЕНИЙ

                except Exception as e:
                    logger.error(f"Ошибка при анализе темы {thread_id}: {e}")
                    continue

            # Формируем итоговый отчёт (без "Всего обработано тем", просто "Всего тем")
            page_word = "страницу" if pages == 1 else f"страниц: {pages}"

            msg = (
                f"🔱 Статистика Судебных исков | Arizona №26 [Faraway] 🔱\n\n"
                f"📊 Просканировано {page_word}\n"
                f"📩 Всего тем: {total_threads}\n"
                f"🔐 Закрыто: {closed_count}\n"
                f"🔓 Открыто: {open_count}\n\n"
            )

            if closed_count > 0:
                sorted_stats = sorted(
                    closed_by_stats.items(), key=lambda x: x[1], reverse=True
                )

                for i, (closer, count) in enumerate(sorted_stats, 1):
                    percentage = count / closed_count * 100

                    # Склонение слова "иск"
                    if count % 10 == 1 and count % 100 != 11:
                        word = "иск"
                    elif 2 <= count % 10 <= 4 and (
                        count % 100 < 10 or count % 100 >= 20
                    ):
                        word = "иска"
                    else:
                        word = "исков"

                    # Номера с эмодзи (для первых 9)
                    if i <= 9:
                        num_emoji = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣"][i - 1]
                        msg += f"{num_emoji} {closer} закрыл(-а) {count} {word} [~{percentage:.0f}%]\n"
                    else:
                        msg += f"{i}. {closer} закрыл(-а) {count} {word} [~{percentage:.0f}%]\n"
            else:
                msg += "📭 На просканированных страницах нет закрытых исков"

            # Отправляем второе сообщение с результатом
            self.send_message(peer_id, msg)
            logger.info(f"ГОТОВО: закрытых тем={closed_count}, открытых={open_count}")

        except Exception as e:
            logger.error(f"Критическая ошибка: {traceback.format_exc()}")
            self.send_message(peer_id, f"❌ Ошибка: {str(e)[:100]}")

    async def _edit_message(self, message_id, peer_id, new_text):
        """Безопасно редактирует сообщение"""
        try:
            self.vk.messages.edit(
                peer_id=peer_id, message_id=message_id, message=new_text
            )
            await asyncio.sleep(0.5)
        except Exception as e:
            logger.error(f"Ошибка редактирования: {e}")

    # Функция для получения ID текущего чата
    async def get_chat_id(self, event):
        peer_id = event.object.message["peer_id"]
        if peer_id >= 2000000000:
            chat_id = peer_id - 2000000000
            return f"Беседа #{chat_id} (peer_id: {peer_id})"
        else:
            return f"Личка с id{peer_id}"

    async def handle_notify_command(self, peer_id, user_id, text, user_display):
        """Обрабатывает команду /notif для отправки повесток"""

        from users_db import get_role_chat

        # Получаем ID беседы админов из БД
        admin_peer_id = get_role_chat('admin')

        if not admin_peer_id:
            self.send_message(
                peer_id, "❌ Беседа администрации не зарегистрирована. Используйте /regadmin"
            )
            return

        # Получаем ID беседы судей из БД для проверки
        judge_chat_id = get_role_chat('judge')

        if not judge_chat_id:
            self.send_message(
                peer_id, "❌ Беседа судей не зарегистрирована. Используйте /regcourt"
            )
            return

        # Проверяем, что команда вызвана в беседе судей
        if peer_id != judge_chat_id:
            self.send_message(
                peer_id, "❌ Команда /notif работает только в беседе судей"
            )
            return

        # Проверяем, является ли пользователь судьей
        if not is_user_allowed(user_id):
            self.send_message(peer_id, "⛔ Только судьи могут использовать эту команду")
            return

        # Парсим команду - убираем "/notif " из начала
        command_text = text[6:].strip()

        if not command_text:
            self.send_message(
                peer_id,
                "❌ Неправильный формат. Используй: /notif Nick_Name Текст сообщения"
            )
            return

        # Разделяем на ник и текст сообщения
        parts = command_text.split(maxsplit=1)
        if len(parts) < 2:
            self.send_message(
                peer_id,
                "❌ Неправильный формат. Используй: /notif Nick_Name Текст сообщения"
            )
            return

        target_nickname = parts[0]
        message_text = parts[1]

        # Сохраняем в базу (существующий код)
        conn = None
        try:
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS notifications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    judge_id INTEGER NOT NULL,
                    judge_peer_id INTEGER,
                    judge_name TEXT NOT NULL,
                    target_nickname TEXT NOT NULL,
                    message TEXT NOT NULL,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    processed_by INTEGER,
                    processed_by_name TEXT,
                    processed_at TIMESTAMP,
                    reject_reason TEXT
                )
            ''')

            cursor.execute('''
                INSERT INTO notifications (judge_id, judge_peer_id, judge_name, target_nickname, message, status)
                VALUES (?, ?, ?, ?, ?, 'pending')
            ''', (user_id, peer_id, user_display, target_nickname, message_text))

            notification_id = cursor.lastrowid
            conn.commit()
            logger.info(f"✅ Повестка #{notification_id} сохранена в БД")

        except Exception as e:
            logger.error(f"Ошибка БД: {e}")
            self.send_message(peer_id, "❌ Ошибка при сохранении в базу данных")
            return
        finally:
            if conn:
                conn.close()

        keyboard = self.create_notify_keyboard(notification_id, user_id, peer_id)

        game_message = f"/notif {target_nickname} {message_text}"

        admin_message = (
            f"📢 НОВАЯ ПОВЕСТКА В СУД #{notification_id} 📢\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"👨‍⚖️ Судья: {user_display}\n"
            f"👤 Ответчик: {target_nickname}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📋 ГОТОВЫЙ ТЕКСТ ДЛЯ ОТПРАВКИ В ИГРЕ:\n"
            f"```\n{game_message}\n```"
        )

        try:
            # Отправляем сообщение в беседу админов
            sent_message = self.vk.messages.send(
                peer_id=admin_peer_id,
                message=admin_message,
                keyboard=keyboard.get_keyboard(),
                random_id=get_random_id(),
            )

            logger.info(f"✅ Сообщение отправлено в беседу админов {admin_peer_id}, ID: {sent_message}")

        except Exception as e:
            logger.error(f"❌ Критическая ошибка отправки в беседу админов: {e}")
            self.send_message(peer_id, "❌ Не удалось отправить в беседу администрации")
            return

        confirm_message = f"✅ Повестка #{notification_id} для {target_nickname} отправлена администрации"
        self.send_message(peer_id, confirm_message)

        # Логируем
        await self.logger.log_action(
            "notify_sent",
            user_display,
            f"Повестка для {target_nickname}",
            f"ID: {notification_id}",
            source_peer_id=peer_id,
        )

    def create_notify_keyboard(self, notification_id, judge_id, judge_peer_id=None):
        """Создает клавиатуру для обработки повестки"""
        keyboard = VkKeyboard(inline=True)

        # Кнопка принятия
        keyboard.add_button(
            "✅ Принять повестку",
            color=VkKeyboardColor.POSITIVE,
            payload={
                "cmd": "accept_notify",
                "notification_id": notification_id,
                "judge_id": judge_id,
                "judge_peer_id": judge_peer_id,
            },
        )

        # Кнопка отклонения
        keyboard.add_button(
            "❌ Отклонить",
            color=VkKeyboardColor.NEGATIVE,
            payload={
                "cmd": "reject_notify",
                "notification_id": notification_id,
                "judge_id": judge_id,
                "judge_peer_id": judge_peer_id,
            },
        )

        return keyboard

    async def handle_notify_callback(self, peer_id, user_id, payload, user_display):
        """Обрабатывает нажатия на кнопки повесток"""

        logger.info(f"Обработка callback повестки: {payload}")

        cmd = payload.get("cmd")
        notification_id = payload.get("notification_id")
        judge_id = payload.get("judge_id")
        judge_peer_id = payload.get("judge_peer_id")

        if not notification_id:
            self.send_message(peer_id, "❌ Ошибка: ID уведомления не найден")
            return

        # Проверяем, что пользователь - админ
        if not check_admin(user_id):
            self.send_message(
                peer_id, "⛔ Только администрация может обрабатывать повестки"
            )
            return

        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()

        # Получаем информацию о повестке
        cursor.execute(
            """
            SELECT judge_id, judge_peer_id, judge_name, target_nickname, message, status 
            FROM notifications WHERE id = ?
        """,
            (notification_id,),
        )

        notify = cursor.fetchone()
        if not notify:
            self.send_message(peer_id, "❌ Повестка не найдена")
            conn.close()
            return

        judge_db_id, judge_db_peer_id, judge_name, target_nickname, message, status = (
            notify
        )

        if status != "pending":
            status_text = "принята" if status == "accepted" else "отклонена"
            self.send_message(peer_id, f"⚠️ Эта повестка уже {status_text}")
            conn.close()
            return

        if cmd == "accept_notify":
            # Обновляем статус
            cursor.execute(
                """
                UPDATE notifications 
                SET status = 'accepted', processed_by = ?, processed_by_name = ?, processed_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """,
                (user_id, user_display, notification_id),
            )
            conn.commit()
            conn.close()

            # Формируем готовый текст для отправки в игре
            game_message = f"/notif {target_nickname} {message}"

            # Получаем текущее время для красивого отображения
            current_time = datetime.now().strftime("%d.%m.%Y %H:%M")

            # ПОДТВЕРЖДЕНИЕ АДМИНУ
            self.send_message(
                peer_id, f"✅ Повестка #{notification_id} для {target_nickname} принята"
            )

            # УВЕДОМЛЕНИЕ СУДЬЕ
            try:
                judge_message = (
                    f"✅ Повестка #{notification_id} для {target_nickname} ПРИНЯТА\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"👨‍⚖️ Судья: {judge_name}\n"
                    f"👤 Ответчик: {target_nickname}\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"✅ Принял: {user_display}\n"
                    f"🕐 Время: {current_time}\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━\n"
                )
                self.send_message(judge_db_peer_id, judge_message)
                logger.info(
                    f"✅ Уведомление отправлено судье в беседу {judge_db_peer_id}"
                )
            except Exception as e:
                logger.error(f"❌ Не удалось отправить уведомление судье: {e}")

            # Логируем
            await self.logger.log_action(
                "notify_accepted",
                user_display,
                f"Повестка #{notification_id} для {target_nickname}",
                f"Судья: {judge_name}",
                source_peer_id=peer_id,
            )

        elif cmd == "reject_notify":
            # Сохраняем данные для отказа
            self.user_data[user_id] = {
                "action": "reject_notify_reason",
                "notification_id": notification_id,
                "judge_id": judge_db_peer_id,  # ID беседы судьи
                "judge_name": judge_name,
                "target_nickname": target_nickname,
                "message": message,
            }

            self.send_message(peer_id, "📝 Укажите причину отказа (одним сообщением):")
            conn.close()

    async def handle_reject_reason(self, peer_id, user_id, text, user_display):
        """Обрабатывает причину отказа от повестки"""

        if (
            user_id not in self.user_data
            or self.user_data[user_id].get("action") != "reject_notify_reason"
        ):
            return False

        data = self.user_data[user_id]
        notification_id = data["notification_id"]
        judge_id = data["judge_id"]  # ID беседы судьи
        judge_name = data["judge_name"]
        target_nickname = data["target_nickname"]
        message = data["message"]
        conversation_message_id = data.get("conversation_message_id")
        reject_reason = text.strip()

        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()

        # Обновляем статус
        cursor.execute(
            """
            UPDATE notifications 
            SET status = 'rejected', 
                processed_by = ?, 
                processed_by_name = ?, 
                processed_at = CURRENT_TIMESTAMP,
                reject_reason = ?
            WHERE id = ?
        """,
            (user_id, user_display, reject_reason, notification_id),
        )

        conn.commit()
        conn.close()

        current_time = datetime.now().strftime("%d.%m.%Y %H:%M")

        try:
            if conversation_message_id:
                edited_message = (
                    f"📢 ПОВЕСТКА В СУД #{notification_id} ❌ ОТКЛОНЕНА\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"👨‍⚖️ Судья: {judge_name}\n"
                    f"👤 Ответчик: {target_nickname}\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"❌ Отклонил: {user_display}\n"
                    f"📌 Причина: {reject_reason}\n"
                    f"🕐 Время: {current_time}"
                )
                self.vk.messages.edit(
                    peer_id=peer_id,
                    conversation_message_id=conversation_message_id,
                    message=edited_message,
                    keyboard=self.vk.keyboard.get_empty(),  # Убираем кнопки
                )
                logger.info(
                    f"✅ Сообщение #{conversation_message_id} отредактировано в беседе админов"
                )
        except Exception as e:
            logger.error(f"❌ Не удалось отредактировать сообщение: {e}")

        # УВЕДОМЛЕНИЕ СУДЬЕ
        try:
            judge_message = (
                f"❌ Повестка #{notification_id} для {target_nickname} ОТКЛОНЕНА\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"👨‍⚖️ Судья: {judge_name}\n"
                f"👤 Ответчик: {target_nickname}\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"❌ Отклонил: {user_display}\n"
                f"📌 Причина: {reject_reason}\n"
                f"🕐 Время: {current_time}"
            )
            self.send_message(judge_id, judge_message)
            logger.info(f"✅ Уведомление об отказе отправлено судье {judge_id}")
        except Exception as e:
            logger.error(f"❌ Не удалось отправить уведомление судье {judge_id}: {e}")

        # ПОДТВЕРЖДЕНИЕ АДМИНУ
        if not conversation_message_id:
            self.send_message(
                peer_id,
                f"✅ Повестка #{notification_id} для {target_nickname} отклонена",
            )

        # Логируем
        await self.logger.log_action(
            "notify_rejected",
            user_display,
            f"Повестка #{notification_id} для {target_nickname}",
            f"Причина: {reject_reason}",
            source_peer_id=peer_id,
        )

        # Очищаем данные пользователя
        del self.user_data[user_id]

        return True

    # Добавьте этот метод в класс ForumBot

    async def handle_notify_all(self, peer_id, user_id, user_display):
        """Показывает все повестки для администраторов (компактный вид)"""

        # Проверяем, админ ли пользователь
        if not check_admin(user_id):
            self.send_message(
                peer_id, "⛔ Только администраторы могут просматривать все повестки"
            )
            return

        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()

        # Получаем все повестки, сортируем по дате (сначала новые)
        cursor.execute("""
            SELECT id, judge_name, judge_id, target_nickname, message, status, 
                   created_at, processed_by_name, reject_reason
            FROM notifications 
            ORDER BY created_at DESC
            LIMIT 50
        """)

        notifications = cursor.fetchall()
        conn.close()

        if not notifications:
            self.send_message(peer_id, "📭 Нет отправленных повесток")
            return

        # Считаем статистику
        pending = sum(1 for n in notifications if n[5] == "pending")
        accepted = sum(1 for n in notifications if n[5] == "accepted")
        rejected = sum(1 for n in notifications if n[5] == "rejected")

        # Формируем сообщение
        msg = "📋 ВСЕ ПОВЕСТКИ (последние 50)\n"
        msg += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        msg += f"📊 Статистика: ⏳{pending} | ✅{accepted} | ❌{rejected}\n"
        msg += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"

        for n in notifications:
            (
                n_id,
                judge_name,
                judge_id,
                target,
                message,
                status,
                created,
                processed_by,
                reason,
            ) = n

            # Обрезаем длинное сообщение
            short_message = message[:35] + "..." if len(message) > 35 else message

            # Выбираем эмодзи и статус
            if status == "pending":
                status_emoji = "⏳"
                status_text = "ожидает"
                processed_info = ""
            elif status == "accepted":
                status_emoji = "✅"
                status_text = "принята"
                processed_info = f" ✅{processed_by}" if processed_by else ""
            else:  # rejected
                status_emoji = "❌"
                status_text = "отклонена"
                short_reason = (
                    reason[:20] + "..." if reason and len(reason) > 20 else reason
                )
                processed_info = f" ❌{processed_by}" if processed_by else ""
                if reason:
                    processed_info += f" [{short_reason}]"

            # Компактная строка: [ID] Статус Судья → Ответчик: текст
            msg += f"{status_emoji} #{n_id} {status_text}\n"
            msg += f"   👨‍⚖️ {judge_name} → {target}\n"
            msg += f"   📝 {short_message}{processed_info}\n"
            msg += f"   📅 {created[:16]}\n\n"

            # Защита от слишком длинного сообщения
            if len(msg) > 3500:
                self.send_message(peer_id, msg)
                msg = ""

        if msg:
            self.send_message(peer_id, msg)

    async def handle_notify_status(self, peer_id, user_id, user_display):
        """Показывает статус всех повесток судьи"""

        if not is_user_allowed(user_id):
            self.send_message(
                peer_id, "⛔ Только судьи могут просматривать статус повесток"
            )
            return

        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()

        # Получаем последние 10 повесток этого судьи
        cursor.execute(
            """
            SELECT id, target_nickname, message, status, created_at, 
                   processed_by_name, reject_reason
            FROM notifications 
            WHERE judge_id = ?
            ORDER BY created_at DESC
            LIMIT 10
        """,
            (user_id,),
        )

        notifications = cursor.fetchall()
        conn.close()

        if not notifications:
            self.send_message(peer_id, "📭 У вас нет отправленных повесток")
            return

        # Формируем сообщение со списком повесток
        status_text = "📋 ВАШИ ПОСЛЕДНИЕ ПОВЕСТКИ\n"
        status_text += "━━━━━━━━━━━━━━━━━━━━━━\n\n"

        for n in notifications:
            n_id, target, message, status, created, processed_by, reason = n

            # Обрезаем длинное сообщение для компактности
            short_message = message[:50] + "..." if len(message) > 50 else message

            # Выбираем эмодзи в зависимости от статуса
            if status == "pending":
                status_emoji = "⏳"
                status_text_local = "Ожидает"
            elif status == "accepted":
                status_emoji = "✅"
                status_text_local = "Принята"
            else:  # rejected
                status_emoji = "❌"
                status_text_local = "Отклонена"

            # Формируем строку для каждой повестки
            status_text += f"{status_emoji} Повестка #{n_id} ({status_text_local})\n"
            status_text += f"👤 Ответчик: {target}\n"
            status_text += f"📝 Текст: {short_message}\n"
            status_text += f"📅 Отправлена: {created[:16]}\n"

            if status == "accepted" and processed_by:
                status_text += f"   ✅ Принял: {processed_by}\n"
            elif status == "rejected" and processed_by:
                status_text += f"   ❌ Отклонил: {processed_by}\n"
                if reason:
                    status_text += f"   📌 Причина: {reason}\n"

            status_text += "\n"

            # Защита от слишком длинного сообщения
            if len(status_text) > 3500:
                self.send_message(peer_id, status_text)
                status_text = ""  # начинаем новое сообщение

        if status_text:  # отправляем остаток
            self.send_message(peer_id, status_text)

    async def handle_notify_delete_single(
        self, peer_id, user_id, notification_id, user_display, parts=None
    ):
        """Удаляет конкретную повестку по ID"""

        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()

        # Проверяем, что повестка принадлежит этому судье
        cursor.execute(
            """
            SELECT target_nickname, status
            FROM notifications 
            WHERE id = ? AND judge_id = ?
        """,
            (notification_id, user_id),
        )

        notify = cursor.fetchone()

        if not notify:
            self.send_message(peer_id, f"❌ Повестка #{notification_id} не найдена")
            conn.close()
            return

        target_nickname, status = notify

        # Удаляем повестку
        cursor.execute("DELETE FROM notifications WHERE id = ?", (notification_id,))
        conn.commit()
        conn.close()

        self.send_message(
            peer_id, f"✅ Повестка #{notification_id} для {target_nickname} удалена"
        )

        # Логируем
        await self.logger.log_action(
            "notify_deleted_single",
            user_display,
            f"Повестка #{notification_id} для {target_nickname}",
            "Удалена через команду",
            source_peer_id=peer_id,
        )

    async def handle_admin_commands(
        self, peer_id, user_id, command, target_username, extra, admin_display, parts=None
    ):
        """Обрабатывает админские команды с username"""

        from database import (
            get_vk_id_by_username,
            add_user,
            remove_user_by_username,
            get_all_users,
        )

        if command == "!addcourt":
            try:
                clean_username = (
                    target_username.replace("@", "")
                    .replace("[id", "")
                    .replace("|", " ")
                    .split()[0]
                )
                search_username = clean_username.lower()
                note_text = (
                    extra if extra else f"Судья с {datetime.now().strftime('%d.%m.%Y')}"
                )

                # Получаем пользователя через VK API
                users = self.vk.users.get(user_ids=search_username)
                if not users:
                    self.send_message(
                        peer_id, f"❌ Пользователь @{clean_username} не найден"
                    )
                    return

                target_user = users[0]
                target_id = target_user["id"]
                target_screen_name = target_user.get("screen_name", str(target_id))
                target_name = f"{target_user['first_name']} {target_user['last_name']}"

                conn = sqlite3.connect(DB_FILE)
                cursor = conn.cursor()

                cursor.execute("SELECT vk_id FROM users WHERE vk_id = ?", (target_id,))
                exists = cursor.fetchone()

                if exists:
                    cursor.execute(
                        """
                        UPDATE users 
                        SET username = ?, is_judge = 1, note = ?
                        WHERE vk_id = ?
                        """,
                        (target_screen_name, note_text, target_id),
                    )
                else:
                    cursor.execute(
                        """
                        INSERT INTO users (vk_id, username, added_by, added_date, last_used, is_judge, note)
                        VALUES (?, ?, ?, ?, ?, 1, ?)
                        """,
                        (
                            target_id,
                            target_screen_name,
                            user_id,
                            datetime.now().isoformat(),
                            datetime.now().isoformat(),
                            note_text,
                        ),
                    )

                conn.commit()
                conn.close()

                display_name = f"[id{target_id}|@{target_screen_name}]"

                self.send_message(
                    peer_id,
                    f"⚖️ Пользователь {display_name} теперь судья\n📝 Должность: {note_text}",
                )

                await self.logger.log_action(
                    "make_judge",
                    admin_display,
                    f"{target_name} (@{target_screen_name})",
                    f"Должность: {note_text}",
                    source_peer_id=peer_id,
                )

            except Exception as e:
                self.send_message(peer_id, f"❌ Ошибка: {e}")
                logger.error(f"Ошибка в addcourt: {traceback.format_exc()}")

        elif command == "!deluser":
            try:
                # Убираем @ если есть
                clean_username = (
                    target_username.lower()
                    .replace("@", "")
                    .replace("[id", "")
                    .replace("|", " ")
                    .split()[0]
                )

                logger.info(f"Попытка удалить пользователя @{clean_username}")

                # Подключаемся к БД
                conn = sqlite3.connect(DB_FILE)
                cursor = conn.cursor()

                # Ищем пользователя по username (в нижнем регистре)
                cursor.execute(
                    "SELECT vk_id, username FROM users WHERE LOWER(username) = ?",
                    (clean_username,),
                )
                user = cursor.fetchone()

                if user:
                    vk_id, db_username = user

                    # Удаляем пользователя
                    cursor.execute("DELETE FROM users WHERE vk_id = ?", (vk_id,))
                    conn.commit()

                    success_msg = f"✅ Пользователь @{db_username} удален из БД"
                    self.send_message(peer_id, success_msg)

                    logger.info(f"Пользователь {vk_id} (@{db_username}) удален")

                    # Логируем
                    await self.logger.log_action(
                        "remove_user",
                        admin_display,
                        f"@{db_username}",
                        "Успешно",
                        source_peer_id=peer_id,
                    )
                else:
                    # Если не нашли по username, пробуем найти по VK API
                    try:
                        # Пробуем найти пользователя через VK API
                        users = self.vk.users.get(user_ids=clean_username)
                        if users:
                            target_id = users[0]["id"]

                            # Ищем по VK ID
                            cursor.execute(
                                "SELECT username FROM users WHERE vk_id = ?",
                                (target_id,),
                            )
                            user_by_id = cursor.fetchone()

                            if user_by_id:
                                cursor.execute(
                                    "DELETE FROM users WHERE vk_id = ?", (target_id,)
                                )
                                conn.commit()
                                success_msg = (
                                    f"✅ Пользователь с ID {target_id} удален из БД"
                                )
                                self.send_message(peer_id, success_msg)

                                logger.info(f"Пользователь {target_id} удален по ID")

                                await self.logger.log_action(
                                    "remove_user",
                                    admin_display,
                                    f"id{target_id}",
                                    "Успешно",
                                    source_peer_id=peer_id,
                                )
                            else:
                                self.send_message(
                                    peer_id,
                                    f"❌ Пользователь @{clean_username} не найден в БД",
                                )
                        else:
                            self.send_message(
                                peer_id, f"❌ Пользователь @{clean_username} не найден"
                            )
                    except Exception as api_error:
                        self.send_message(
                            peer_id, f"❌ Пользователь @{clean_username} не найден"
                        )

                conn.close()

            except Exception as e:
                error_msg = f"❌ Ошибка: {str(e)}"
                self.send_message(peer_id, error_msg)
                logger.error(f"Ошибка в deluser: {traceback.format_exc()}")

        elif command == "!addadmin":
            try:
                # Убираем @ если есть
                clean_username = (
                    target_username.replace("@", "")
                    .replace("[id", "")
                    .replace("|", " ")
                    .split()[0]
                )

                # Для поиска используем нижний регистр
                search_username = clean_username.lower()

                # Для заметки используем оригинальный текст без изменения регистра
                note_text = (
                    extra if extra else f"Админ с {datetime.now().strftime('%d.%m.%Y')}"
                )

                # Пробуем найти пользователя через VK
                users = self.vk.users.get(user_ids=search_username)
                if not users:
                    self.send_message(
                        peer_id, f"❌ Пользователь @{clean_username} не найден"
                    )
                    return

                target_user = users[0]
                target_id = target_user["id"]
                target_screen_name = target_user.get("screen_name", str(target_id))
                target_name = f"{target_user['first_name']} {target_user['last_name']}"

                # Сохраняем в БД
                conn = sqlite3.connect(DB_FILE)
                cursor = conn.cursor()

                cursor.execute("SELECT vk_id FROM users WHERE vk_id = ?", (target_id,))
                exists = cursor.fetchone()

                if exists:
                    cursor.execute(
                        """
                UPDATE users 
                SET username = ?, is_admin = 1, note = ?
                WHERE vk_id = ?
              """,
                        (target_screen_name, note_text, target_id),
                    )
                    logger.info(f"Обновлен админ {target_id}, заметка: {note_text}")
                else:
                    cursor.execute(
                        """
                INSERT INTO users (vk_id, username, added_by, added_date, last_used, is_admin, note)
                VALUES (?, ?, ?, ?, ?, 1, ?)
              """,
                        (
                            target_id,
                            target_screen_name,
                            user_id,
                            datetime.now().isoformat(),
                            datetime.now().isoformat(),
                            note_text,
                        ),
                    )
                    logger.info(f"Добавлен админ {target_id}, заметка: {note_text}")

                conn.commit()
                conn.close()

                # Делаем красивое отображение
                if target_screen_name and target_screen_name != str(target_id):
                    display_name = f"[id{target_id}|@{target_screen_name}]"
                else:
                    display_name = f"[id{target_id}|{target_name}]"

                self.send_message(
                    peer_id,
                    f"👑 Пользователь {display_name} теперь админ\n📝 Заметка: {note_text}",
                )

                await self.logger.log_action(
                    "make_admin",
                    admin_display,
                    f"{target_name} (@{target_screen_name})",
                    f"Заметка: {note_text}",
                    source_peer_id=peer_id,
                )

            except Exception as e:
                self.send_message(peer_id, f"❌ Ошибка: {e}")
                logger.error(f"Ошибка в addadmin: {traceback.format_exc()}")

        elif command == "!court":
            from users_db import get_all_judges

            judges = get_all_judges()
            if not judges:
                self.send_message(peer_id, "📭 Судей нет")
                return

            msg = "⚖️ Судьи\n\n"

            for vk_id, username, added_date, last_used, note in judges:
                date_str = added_date[:10] if added_date else "неизвестно"
                note_str = f" — {note}" if note else ""

                try:
                    user_info = self.vk.users.get(user_ids=vk_id)[0]
                    first_name = user_info.get("first_name", "")
                    last_name = user_info.get("last_name", "")
                    screen_name = user_info.get("screen_name", "")

                    if screen_name:
                        display_name = f"[id{vk_id}|@{screen_name}]"
                        full_name = f"{first_name} {last_name}".strip()
                        name_part = f" ({full_name})" if full_name else ""
                    else:
                        full_name = f"{first_name} {last_name}".strip()
                        display_name = f"[id{vk_id}|{full_name or f'id{vk_id}'}]"
                        name_part = ""
                except:
                    display_name = f"[id{vk_id}|id{vk_id}]"
                    name_part = ""

                msg += f"⚖️ {display_name}{name_part}{note_str}\n"
                msg += f"📅 С {date_str}\n\n"

            self.send_message(peer_id, msg)

        elif command == "!addatt":
            try:
                # Убираем @ если есть
                clean_username = (
                    target_username.replace("@", "")
                    .replace("[id", "")
                    .replace("|", " ")
                    .split()[0]
                )
                search_username = clean_username.lower()
                note_text = (
                    extra
                    if extra
                    else f"Атторней с {datetime.now().strftime('%d.%m.%Y')}"
                )

                # Пробуем найти пользователя через VK
                users = self.vk.users.get(user_ids=search_username)
                if not users:
                    self.send_message(
                        peer_id, f"❌ Пользователь @{clean_username} не найден"
                    )
                    return

                target_user = users[0]
                target_id = target_user["id"]
                target_screen_name = target_user.get("screen_name", str(target_id))
                target_name = f"{target_user['first_name']} {target_user['last_name']}"

                # Обновляем в БД
                conn = sqlite3.connect(DB_FILE)
                cursor = conn.cursor()

                # Проверяем, есть ли пользователь
                cursor.execute("SELECT vk_id FROM users WHERE vk_id = ?", (target_id,))
                exists = cursor.fetchone()

                if exists:
                    cursor.execute(
                        """
                        UPDATE users 
                        SET username = ?, is_attorney = 1, note = ?
                        WHERE vk_id = ?
                    """,
                        (target_screen_name, note_text, target_id),
                    )
                    logger.info(f"Обновлен атторней {target_id}, заметка: {note_text}")
                else:
                    cursor.execute(
                        """
                        INSERT INTO users (vk_id, username, added_by, added_date, last_used, is_attorney, note)
                        VALUES (?, ?, ?, ?, ?, 1, ?)
                    """,
                        (
                            target_id,
                            target_screen_name,
                            user_id,
                            datetime.now().isoformat(),
                            datetime.now().isoformat(),
                            note_text,
                        ),
                    )
                    logger.info(f"Добавлен атторней {target_id}, заметка: {note_text}")

                conn.commit()
                conn.close()

                # Делаем красивое отображение
                if target_screen_name and target_screen_name != str(target_id):
                    display_name = f"[id{target_id}|@{target_screen_name}]"
                else:
                    display_name = f"[id{target_id}|{target_name}]"

                self.send_message(
                    peer_id,
                    f"⚖️ Пользователь {display_name} теперь атторней\n📝 Заметка: {note_text}",
                )

                await self.logger.log_action(
                    "make_attorney",
                    admin_display,
                    f"{target_name} (@{target_screen_name})",
                    f"Заметка: {note_text}",
                    source_peer_id=peer_id,
                )

            except Exception as e:
                self.send_message(peer_id, f"❌ Ошибка: {e}")
                logger.error(f"Ошибка в addattorney: {traceback.format_exc()}")

        elif command == "!attorney":
            from users_db import get_all_attorneys

            attorneys = get_all_attorneys()
            if not attorneys:
                self.send_message(peer_id, "📭 Атторнеев нет")
                return

            msg = "⚖️ Атторнеи\n"
            msg += "\n"

            for vk_id, username, added_date, last_used, note in attorneys:
                date_str = added_date[:10] if added_date else "неизвестно"
                note_str = f" - {note}" if note else ""

                # Получаем информацию о пользователе
                try:
                    user_info = self.vk.users.get(user_ids=vk_id)[0]
                    first_name = user_info.get("first_name", "")
                    last_name = user_info.get("last_name", "")
                    screen_name = user_info.get("screen_name", "")

                    if screen_name:
                        display_name = f"[id{vk_id}|@{screen_name}]"
                        full_name = f"{first_name} {last_name}".strip()
                        name_part = f" ({full_name})" if full_name else ""
                    else:
                        full_name = f"{first_name} {last_name}".strip()
                        if full_name:
                            display_name = f"[id{vk_id}|{full_name}]"
                        else:
                            display_name = f"[id{vk_id}|id{vk_id}]"
                        name_part = ""
                except:
                    display_name = f"[id{vk_id}|id{vk_id}]"
                    name_part = ""

                msg += f"⚖️ {display_name}{name_part} (с {date_str}){note_str}\n"

            self.send_message(peer_id, msg)

        elif command == "!addleader":
            try:
                clean_username = (
                    target_username.replace("@", "")
                    .replace("[id", "")
                    .replace("|", " ")
                    .split()[0]
                )
                search_username = clean_username.lower()
                note_text = extra if extra else f"Лидер"

                users = self.vk.users.get(user_ids=search_username)
                if not users:
                    self.send_message(
                        peer_id, f"❌ Пользователь @{clean_username} не найден"
                    )
                    return

                target_user = users[0]
                target_id = target_user["id"]
                target_screen_name = target_user.get("screen_name", str(target_id))
                target_name = f"{target_user['first_name']} {target_user['last_name']}"

                conn = sqlite3.connect(DB_FILE)
                cursor = conn.cursor()

                cursor.execute("SELECT vk_id FROM users WHERE vk_id = ?", (target_id,))
                exists = cursor.fetchone()

                if exists:
                    cursor.execute(
                        """
                        UPDATE users 
                        SET username = ?, is_leader = 1, note = ?
                        WHERE vk_id = ?
                        """,
                        (target_screen_name, note_text, target_id),
                    )
                else:
                    cursor.execute(
                        """
                        INSERT INTO users (vk_id, username, added_by, added_date, last_used, is_leader, note)
                        VALUES (?, ?, ?, ?, ?, 1, ?)
                        """,
                        (
                            target_id,
                            target_screen_name,
                            user_id,
                            datetime.now().isoformat(),
                            datetime.now().isoformat(),
                            note_text,
                        ),
                    )

                conn.commit()
                conn.close()

                display_name = f"[id{target_id}|@{target_screen_name}]"

                self.send_message(
                    peer_id,
                    f"👤 Пользователь {display_name} теперь лидер\n📝 Заметка: {note_text}",
                )

                await self.logger.log_action(
                    "make_leader",
                    admin_display,
                    f"{target_name} (@{target_screen_name})",
                    f"Заметка: {note_text}",
                    source_peer_id=peer_id,
                )

            except Exception as e:
                self.send_message(peer_id, f"❌ Ошибка: {e}")
                logger.error(f"Ошибка в addlead: {traceback.format_exc()}")

        elif command == "!leaders":
            from users_db import get_all_leaders

            leaders = get_all_leaders()
            if not leaders:
                self.send_message(peer_id, "📭 Лидеров нет")
                return

            msg = "👥 Лидеры\n\n"

            for vk_id, username, added_date, last_used, note in leaders:
                date_str = added_date[:10] if added_date else "неизвестно"
                note_str = f" — {note}" if note else ""

                try:
                    user_info = self.vk.users.get(user_ids=vk_id)[0]
                    first_name = user_info.get("first_name", "")
                    last_name = user_info.get("last_name", "")
                    screen_name = user_info.get("screen_name", "")

                    if screen_name:
                        display_name = f"[id{vk_id}|@{screen_name}]"
                        full_name = f"{first_name} {last_name}".strip()
                        name_part = f" ({full_name})" if full_name else ""
                    else:
                        full_name = f"{first_name} {last_name}".strip()
                        display_name = f"[id{vk_id}|{full_name or f'id{vk_id}'}]"
                        name_part = ""
                except:
                    display_name = f"[id{vk_id}|id{vk_id}]"
                    name_part = ""

                msg += f"👤 {display_name}{name_part}{note_str}\n"

            self.send_message(peer_id, msg)

        elif command == "!setpost":
            vk_id = get_vk_id_by_username(target_username)
            if not vk_id:
                self.send_message(peer_id, "❌ Пользователь не найден в базе")
                return

            if not extra:
                self.send_message(
                    peer_id,
                    "❌ Укажи новую должность. Пример: !setpost @user Лидер RCSD",
                )
                return

            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET note = ? WHERE vk_id = ?", (extra, vk_id))
            conn.commit()
            conn.close()

            self.send_message(peer_id, f"📝 Должность обновлена:\n{extra}")

            await self.logger.log_action(
                "set_post",
                admin_display,
                f"vk_id={vk_id}",
                f"Новая должность: {extra}",
                source_peer_id=peer_id,
            )

        elif command == "!rolechats":
            if not check_admin(user_id):
                self.send_message(peer_id, "⛔ Только администраторы могут просматривать список")
                return

            from users_db import get_all_role_chats_with_names

            role_chats = get_all_role_chats_with_names(self.vk)

            if not role_chats:
                self.send_message(peer_id, "📭 Нет зарегистрированных бесед")
                return

            role_names = {
                "leader": "👑 Лидеры",
                "judge": "⚖️ Судьи", 
                "attorney": "📜 Атторнеи",
                "admin": "🛡️ Администраторы",
                "ministry_of_justice": "⚖️ Министерство Юстиций"
            }

            # Разделяем по ролям для лучшей читаемости
            chats_by_role = {}
            for chat_data in role_chats:
                role = chat_data['role']
                if role not in chats_by_role:
                    chats_by_role[role] = []
                chats_by_role[role].append(chat_data)

            msg = "📋 ЗАРЕГИСТРИРОВАННЫЕ БЕСЕДЫ\n"
            msg += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"

            for role in ['admin', 'judge', 'attorney', 'leader', 'ministry_of_justice']:
                if role in chats_by_role:
                    msg += f"{role_names.get(role, role)}\n"

                    for chat_data in chats_by_role[role]:
                        chat_id = chat_data['chat_id']
                        chat_name = chat_data['chat_name']
                        chat_number = chat_id - 2000000000 if chat_id >= 2000000000 else chat_id

                        # Обрезаем длинные названия
                        if len(chat_name) > 30:
                            chat_name = chat_name[:27] + "..."

                        msg += f" {chat_name} [ID:{chat_number}] \n"

                    msg += "\n"

            # Добавляем статистику
            msg += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            msg += f"📊 Всего бесед: {len(role_chats)}"

            self.send_message(peer_id, msg)
            return

        elif command == "!rolechats":
            if not check_admin(user_id):
                self.send_message(peer_id, "⛔ Только администраторы могут просматривать список")
                return

            from users_db import get_all_role_chats_with_names

            role_chats = get_all_role_chats_with_names(self.vk)

            if not role_chats:
                self.send_message(peer_id, "📭 Нет зарегистрированных бесед")
                return

            role_names = {
                "leader": "👑 Лидеры",
                "judge": "⚖️ Судьи", 
                "attorney": "📜 Атторнеи",
                "admin": "🛡️ Администраторы",
                "ministry_of_justice": "⚖️ Министерство Юстиций"
            }

            # Разделяем по ролям для лучшей читаемости
            chats_by_role = {}
            for chat_data in role_chats:
                role = chat_data['role']
                if role not in chats_by_role:
                    chats_by_role[role] = []
                chats_by_role[role].append(chat_data)

            msg = "📋 ЗАРЕГИСТРИРОВАННЫЕ БЕСЕДЫ\n"
            msg += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"

            for role in ['admin', 'judge', 'attorney', 'leader', 'ministry_of_justice']:
                if role in chats_by_role:
                    msg += f"{role_names.get(role, role)}\n"

                    for chat_data in chats_by_role[role]:
                        chat_id = chat_data['chat_id']
                        chat_name = chat_data['chat_name']
                        chat_number = chat_id - 2000000000 if chat_id >= 2000000000 else chat_id

                        # Обрезаем длинные названия
                        if len(chat_name) > 30:
                            chat_name = chat_name[:27] + "..."

                        msg += f" {chat_name} [ID:{chat_number}] \n"

                    msg += "\n"

            # Добавляем статистику
            msg += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            msg += f"📊 Всего бесед: {len(role_chats)}"

            self.send_message(peer_id, msg)
            return

        # Для команды !delrolechat (если добавили)
        if command == "!delrolechat":
            if not check_admin(user_id):
                self.send_message(peer_id, "⛔ Только администраторы могут удалять регистрации")
                return

            # Используем parts, если он передан
            if parts and len(parts) < 2:
                self.send_message(peer_id, "❌ Укажите роль. Пример: !delrolechat judge")
                return

            if not parts:
                self.send_message(peer_id, "❌ Укажите роль. Пример: !delrolechat judge")
                return

            role = parts[1].lower() if len(parts) > 1 else None

            if not role:
                self.send_message(peer_id, "❌ Укажите роль. Пример: !delrolechat judge")
                return

            from users_db import delete_role_chat, get_role_chat

            if not get_role_chat(role):
                self.send_message(peer_id, f"❌ Роль {role} не зарегистрирована")
                return

            delete_role_chat(role)
            self.send_message(peer_id, f"✅ Регистрация беседы для роли {role} удалена")
            return

        elif command == "!admins":
            users = get_all_users()

            admins = [u for u in users if u[5]]  # u[5] это is_admin
            if not admins:
                self.send_message(peer_id, "📭 Админов нет")
                return

            msg = "👑 Администраторы\n"
            msg += "\n"

            for (
                vk_id,
                username,
                added_date,
                last_used,
                note,
                is_admin,
                is_attorney,
            ) in admins:
                date_str = added_date[:10] if added_date else "неизвестно"
                note_str = f" - {note}" if note else ""

                # 👇 ПОЛУЧАЕМ ИНФОРМАЦИЮ О ПОЛЬЗОВАТЕЛЕ ЧЕРЕЗ VK API
                try:
                    user_info = self.vk.users.get(user_ids=vk_id)[0]
                    first_name = user_info.get("first_name", "")
                    last_name = user_info.get("last_name", "")
                    screen_name = user_info.get("screen_name", "")

                    # Формируем красивое отображение
                    if screen_name:
                        display_name = f"[id{vk_id}|@{screen_name}]"
                        full_name = f"{first_name} {last_name}".strip()
                        name_part = f" ({full_name})" if full_name else ""
                    else:
                        full_name = f"{first_name} {last_name}".strip()
                        if full_name:
                            display_name = f"[id{vk_id}|{full_name}]"
                        else:
                            display_name = f"[id{vk_id}|id{vk_id}]"
                        name_part = ""

                    # Обновляем username в базе
                    if screen_name and screen_name != username:
                        conn = sqlite3.connect(DB_FILE)
                        cursor = conn.cursor()
                        cursor.execute(
                            "UPDATE users SET username = ? WHERE vk_id = ?",
                            (screen_name, vk_id),
                        )
                        conn.commit()
                        conn.close()

                except Exception as e:
                    logger.error(f"Ошибка получения данных пользователя {vk_id}: {e}")
                    display_name = f"[id{vk_id}|id{vk_id}]"
                    name_part = ""

                msg += f"👑 {display_name}{name_part} {note_str}\n"

            self.send_message(peer_id, msg)

    # ================= ОБРАБОТКА СООБЩЕНИЙ =================

    async def handle_message(self, event):
        message = event.object.message
        message_id = message.get("id", 0)
        peer_id = message["peer_id"]
        user_id = message["from_id"]
        text = message.get("text", "").strip()
        current_time = time.time()
        cmid = message.get("conversation_message_id")

        # Разрешаем события от бота (from_id < 0)
        if user_id > 0 and not is_user_allowed(user_id):
            logger.warning(f"Отказ в доступе пользователю {user_id}")
            return

        is_chat = peer_id >= 2000000000
        is_private = not is_chat

        text_preview = text[:10] if text else "empty"
        unique_key = f"{message_id}_{peer_id}_{text_preview}"

        if unique_key in self.processed_events:
            time_diff = current_time - self.processed_events[unique_key]
            if time_diff < self.DUPLICATE_TIMEOUT:
                logger.debug(f"Дубль: {unique_key} ({time_diff:.1f} сек)")
                return

        self.processed_events[unique_key] = current_time
        old_keys = [
            k for k, ts in self.processed_events.items() if current_time - ts > 60
        ]
        for k in old_keys:
            del self.processed_events[k]
        if len(self.processed_events) > 1000:
            sorted_keys = sorted(
                self.processed_events.keys(),
                key=lambda k: self.processed_events[k],
                reverse=True,
            )[:500]
            self.processed_events = {k: self.processed_events[k] for k in sorted_keys}

        logger.info(
            f"Обработка сообщения {message_id} от {user_id} в {'беседе' if is_chat else 'личке'}: {text[:50]}"
        )

        try:
            user_info = self.vk.users.get(user_ids=user_id)[0]
            username = (
                f"@{user_info['screen_name']}"
                if user_info.get("screen_name")
                else f"id{user_id}"
            )
            full_name = f"{user_info['first_name']} {user_info['last_name']}"
            user_display = f"{full_name} ({username})"
        except:
            user_display = f"id{user_id}"

        # ожидаем причину отказа по повестке
        if (
            user_id in self.user_data
            and self.user_data[user_id].get("action") == "reject_notify_reason"
        ):
            if await self.handle_reject_reason(peer_id, user_id, text, user_display):
                return

        # ожидаем заполнение постановления
        if user_id in self.user_data:
            data = self.user_data[user_id]
            if data.get("action") == "awaiting_resolution_form":
                await self.handle_resolution_form_step(user_id, text)
                return

        # команда постановлений
        if text.startswith("/res"):
            await self.handle_resolution_command(peer_id, user_id, text, user_display)
            return

        # ожидаем причину удаления темы
        if (
            user_id in self.user_data
            and self.user_data[user_id].get("action") == "awaiting_delete_reason"
        ):
            # здесь переносим твой текущий код удаления темы (thread.delete(reason=...))
            # и очищаем self.user_data[user_id]
            # ...
            return

        # ожидаем новое название теми
        if (
            user_id in self.user_data
            and self.user_data[user_id].get("action") == "awaiting_new_title"
        ):
            data = self.user_data[user_id]
            thread_id = data["thread_id"]
            creator_id = data["creator_id"]
            created_at = data.get("created_at", 0)
            new_title = text.strip()

            # Проверяем, не отмена ли
            if new_title.lower() in ["отмена", "cancel", "-"]:
                self.send_message(peer_id, "❌ Изменение названия отменено")
                del self.user_data[user_id]
                return

            if len(new_title) < 3:
                self.send_message(
                    peer_id, "❌ Название слишком короткое (минимум 3 символа)"
                )
                return

            try:
                thread = await self.forum_api.get_thread(thread_id)
                if not thread:
                    self.send_message(peer_id, f"❌ Тема {thread_id} не найдена")
                    del self.user_data[user_id]
                    return

                # Изменяем название, сохраняя текущий статус
                current_is_closed = getattr(thread, "is_closed", False)
                current_is_sticky = getattr(thread, "is_sticky", False)

                resp = await thread.edit_info(
                    title=new_title,
                    opened=not current_is_closed,  # opened=True значит открыта
                    sticky=current_is_sticky,
                )

                if resp and resp.status == 200:
                    self.send_message(
                        peer_id,
                        f"✅ Название темы {thread_id} изменено на:\n{new_title}",
                    )
                    await self.logger.log_action(
                        "edit_title",
                        user_display,
                        f"Тема {thread_id}",
                        f"Новое название: {new_title[:50]}",
                        source_peer_id=peer_id,
                    )
                else:
                    self.send_message(peer_id, "⚠️ Ошибка при изменении названия")

            except Exception as e:
                logger.error(f"Ошибка изменения названия: {e}")
                self.send_message(peer_id, f"❌ Ошибка: {str(e)[:100]}")
            finally:
                del self.user_data[user_id]
            return

        # callback-кнопки
        if "payload" in message:
            try:
                payload = json.loads(message["payload"])
            except:
                payload = {}
            await self.handle_callback(peer_id, user_id, payload, user_display)
            return

        action = message.get("action")
        if action:
            action_type = action.get("type")
            member_id = action.get("member_id")

            if action_type in ["chat_kick_user", "chat_leave_user"]:
                logger.warning(f"CHAT_LEAVE: member_id={member_id}, peer_id={peer_id}")
                await self.handle_chat_leave(peer_id, member_id)
                return

        if is_chat and cmid:
            await self.maybe_add_reaction(peer_id, cmid, reaction_chance=5)

        if not text:
            return



        # /notif
        if text.startswith("/notif"):
            if is_private:
                self.send_message(
                    peer_id, "❌ Команда /notif работает только в беседе судей"
                )
                return

            # Проверяем через БД
            from users_db import get_role_chat
            judge_chat_id = get_role_chat('judge')

            if not judge_chat_id:
                self.send_message(
                    peer_id, "❌ Беседа судей не зарегистрирована. Используйте /regcourt"
                )
                return

            if peer_id != judge_chat_id:
                self.send_message(
                    peer_id, "❌ Команда /notif работает только в беседе судей"
                )
                return

            await self.handle_notify_command(peer_id, user_id, text, user_display)
            return

        if (
            text.startswith("/regleader")
            or text.startswith("/regcourt")
            or text.startswith("/regatt")
            or text.startswith("/regadmin")
            or text.startswith("/regmy")
        ):
            await self.handle_register_chat(peer_id, user_id, text, user_display)
            return

        if not text.startswith("!"):
            if is_chat:
                return
            else:
                self.send_message(peer_id, "❓ Неизвестная команда. Напиши '!help'.")
                return

        parts = text.split()
        command = parts[0].lower()

        ALLOWED_COMMANDS = [
            "!help",
            "!getid",
            "!info",
            "!edit",
            "!notif",
            "!delnotif",
            "!addcourt",
            "!deluser",
            "!addadmin",
            "!addatt",
            "!attorney",
            "!court",
            "!admins",
            "!setpost",
            "!иски",
            "!reboot",
            "!addleader",
            "!leaders",
            "!rolechats",
            "!delrolechat"
        ]

        if command not in ALLOWED_COMMANDS:
            if is_chat:
                logger.info(f"Игнор неизвестной команды {command} в беседе")
                return
            else:
                self.send_message(
                    peer_id, f"❓ Неизвестная команда '{command}'. Напиши '!help'."
                )
                return

        # 2. Команда !notif status
        if command == "!notif" and len(parts) >= 2 and parts[1] == "status":
            await self.handle_notify_status(peer_id, user_id, user_display)
            return

        if command == "!notif" and len(parts) >= 2 and parts[1] == "all":
            await self.handle_notify_all(peer_id, user_id, user_display)
            return

        # 3. Команда !delnotif
        if command == "!delnotif":
            if len(parts) != 2 or not parts[1].isdigit():
                self.send_message(peer_id, "❌ Используй: !delnotif [ID повестки]")
                return

            if not check_admin(user_id):
                self.send_message(
                    peer_id, "⛔ Только судьи могут использовать эту команду"
                )
                return

            notification_id = int(parts[1])
            await self.handle_notify_delete_single(
                peer_id, user_id, notification_id, user_display
            )
            return

        # 4. АДМИН-КОМАНДЫ
        if command in [
            "!addcourt",
            "!deluser",
            "!addadmin",
            "!court",
            "!admins",
            "!addatt",
            "!attorney",
            "!addleader",
            "!leaders",
            "!setpost",
            "!rolechats",
            "!delrolechat"
        ]:
            if not check_admin(user_id):
                self.send_message(peer_id, "⛔ У тебя нет прав администратора")
                return

            # Команды, которые требуют указания username
            if command in [
                "!addcourt",
                "!deluser",
                "!addadmin",
                "!addatt",
                "!addleader",
                "!setpost",
            ]:
                if len(parts) < 2:
                    self.send_message(
                        peer_id, f"❌ Укажи username. Пример: `{command} @username`"
                    )
                    return

                target_username = parts[1]
                extra = " ".join(parts[2:]) if len(parts) > 2 else ""
                await self.handle_admin_commands(
                    peer_id, user_id, command, target_username, extra, user_display, parts
                )

            else:
                # court, admins, attorney, leaders
                await self.handle_admin_commands(
                    peer_id, user_id, command, "", "", user_display, parts
                )

            return

        # help
        if command == "!help":
            await self.show_help(peer_id)
            return

        if command == "!getid":
            if is_chat:
                chat_id = peer_id - 2000000000
                resp = f"📌 ID этой беседы:\n• peer_id: {peer_id}\n• chat_id: {chat_id}"
            else:
                resp = f"📌 Это личные сообщения\n• peer_id: {peer_id}"
            self.send_message(peer_id, resp)
            return

        if command == "!иски":
            pages = 1
            if len(parts) >= 3:
                try:
                    pages = int(parts[2])
                except ValueError:
                    self.send_message(
                        peer_id, "❌ Количество страниц должно быть числом"
                    )
                    return
            await self.get_court_stats(peer_id, user_display, pages)
            return

        if command == "!reboot":
            if not check_admin(user_id):
                self.send_message(
                    peer_id, "⛔ Только администраторы могут перезапускать бота"
                )
                return
            kb = VkKeyboard(inline=True)
            kb.add_button(
                "✅ Да, перезапустить",
                color=VkKeyboardColor.NEGATIVE,
                payload={"cmd": "confirm_reboot", "user_id": user_id},
            )
            kb.add_button(
                "❌ Отмена",
                color=VkKeyboardColor.POSITIVE,
                payload={"cmd": "cancel_reboot"},
            )
            self.send_message(
                peer_id,
                "⚠️ ВНИМАНИЕ! Перезапуск бота приведет к временной недоступности.\n"
                "Все текущие операции будут прерваны.\n\n"
                "Подтвердите перезапуск:",
                kb,
            )
            return

        if command in ["!info", "!edit"]:
            if len(parts) < 2:
                self.send_message(
                    peer_id,
                    f"❌ Укажи ссылку на тему. Пример: `{command} https://forum.arizona-rp.com/threads/10673369/`",
                )
                return

            thread_id = self.extract_thread_id_from_url(parts[1])
            if not thread_id:
                self.send_message(peer_id, "❌ Не удалось распознать ID темы.")
                return

        if command == "!info":
            # Для !info - только информация, кнопки только для админов
            await self.show_thread_info(
                peer_id, user_id, thread_id, user_display, show_keyboard=True
            )
        else:  # !edit
            # Проверяем права доступа к теме
            user_is_admin = check_admin(user_id)
            is_allowed, error_message, access_status = await self.is_thread_allowed(
                thread_id, user_id, user_is_admin
            )

            if not is_allowed:
                if access_status == "not_found":
                    self.send_message(
                        peer_id,
                        f"❌ Тема {thread_id} не найдена или нет прав на просмотр.",
                    )
                else:
                    self.send_message(peer_id, error_message)
                return

            # Для !edit - всегда 2 базовые кнопки
            kb = self.create_action_keyboard(thread_id, user_id)

            self.send_message(
                peer_id, f"Какое действие вы хотите совершить с этой темой?", kb
            )
        return

        self.send_message(peer_id, "❓ Неизвестная команда. Напиши '!help'.")

    async def run(self):
        logger.info("=" * 50)
        logger.info("ЗАПУСК БОТА")
        logger.info("=" * 50)

        try:
            logger.info("Подключение к форуму...")
            await self.forum_api.connect()
            logger.info("✅ Подключение к форуму установлено")
        except Exception as e:
            logger.error(f"❌ Не удалось подключиться к форуму: {e}")
            await asyncio.sleep(60)
            return

        logger.info("🤖 Бот запущен и ожидает сообщения...")

        while True:
            try:
                for event in self.longpoll.listen():
                    if event.type == VkBotEventType.MESSAGE_NEW:
                        await self.handle_message(event)

                    elif event.type == VkBotEventType.GROUP_JOIN:
                        logger.info(f"GROUP_JOIN: {event.object}")

                    elif event.type == VkBotEventType.GROUP_LEAVE:
                        logger.info(
                            f"GROUP_LEAVE: user_id={event.object.user_id}, peer_id={event.object.peer_id}"
                        )
                        await self.handle_group_leave(event)

            except Exception:
                logger.error(f"Ошибка в основном цикле: {traceback.format_exc()}")
                await asyncio.sleep(10)

init_db()

if __name__ == "__main__":
    bot = ForumBot()
    while True:
        try:
            asyncio.run(bot.run())
        except KeyboardInterrupt:
            logger.info("Бот остановлен пользователем")
            break
        except Exception:
            logger.error(f"Критическая ошибка: {traceback.format_exc()}")
            time.sleep(30)
