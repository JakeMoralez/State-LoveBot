# logger.py
import logging
from datetime import datetime

class ActionLogger:
    def __init__(self, vk_api, log_chat_id):
        self.vk = vk_api
        self.log_chat = log_chat_id  # ID беседы для логов
        self.logger = logging.getLogger(__name__)

    async def log_action(self, action, user_info, target_info, result, source_peer_id=None):
        """Логирует действие с указанием источника"""
        if not self.log_chat:
            return

        timestamp = datetime.now().strftime("%d.%m.%Y %H:%M:%S")

        # Определяем, откуда пришло действие
        source = "Личные сообщения"
        if source_peer_id and source_peer_id >= 2000000000:
            chat_id = source_peer_id - 2000000000
            source = f"Беседа #{chat_id}"

        # Форматируем сообщение в зависимости от типа действия
        if action in ['add_user', 'remove_user', 'make_admin']:
            emoji = {
                'add_user': '➕',
                'remove_user': '➖',
                'make_admin': '👑'
            }.get(action, '📌')

            msg = (
                f"{emoji} {action.replace('_', ' ').title()}\n"
                f"━━━━━━━━━━━━━━━━\n"
                f"👤 Админ: {user_info}\n"
                f"📍 Источник: {source}\n"
                f"🎯 Цель: {target_info}\n"
                f"✅ Результат: {result}\n"
                f"🕐 Время: {timestamp}"
            )

        elif action in ['close_thread', 'open_thread', 'pin_thread', 'unpin_thread', 'thread_info']:
            emoji = {
                'close_thread': '🔒',
                'open_thread': '🔓',
                'pin_thread': '📌',
                'unpin_thread': '📍',
                'thread_info': 'ℹ️'
            }.get(action, '📌')

            msg = (
                f"{emoji} {action.replace('_', ' ').title()}\n"
                f"━━━━━━━━━━━━━━━━\n"
                f"👤 Пользователь: {user_info}\n"
                f"📍 Источник: {source}\n"
                f"🔗 Тема: {target_info}\n"
                f"✅ Результат: {result}\n"
                f"🕐 Время: {timestamp}"
            )

        elif action in ['access_denied', 'thread_info_error']:
            emoji = '⛔' if action == 'access_denied' else '⚠️'
            msg = (
                f"{emoji} {action.replace('_', ' ').title()}\n"
                f"━━━━━━━━━━━━━━━━\n"
                f"👤 Пользователь: {user_info}\n"
                f"📍 Источник: {source}\n"
                f"📝 Детали: {target_info}\n"
                f"✅ Результат: {result}\n"
                f"🕐 Время: {timestamp}"
            )           

        else:
            msg = (
                f"📌 {action}\n"
                f"━━━━━━━━━━━━━━━━\n"
                f"👤 Пользователь: {user_info}\n"
                f"📍 Источник: {source}\n"
                f"📝 Детали: {target_info}\n"
                f"✅ Результат: {result}\n"
                f"🕐 Время: {timestamp}"
            )

        try:
            self.vk.messages.send(
                peer_id=self.log_chat,
                message=msg,
                random_id=0
            )
        except Exception as e:
            self.logger.error(f"Ошибка отправки лога: {e}")
