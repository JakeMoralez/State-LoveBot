# users_db.py
import sqlite3
import logging  
from database import (
    is_user_allowed,
    is_admin,
    is_user_allowed_by_username,
    is_admin_by_username,
    add_user,
    remove_user_by_username,
    get_all_users,
    get_username_by_vk_id,
    DB_FILE
)

logger = logging.getLogger(__name__)

def check_admin(user_id):
    """Проверяет, является ли пользователь админом по ID"""
    return is_admin(user_id)

def is_user_allowed_by_name(username):
    """Проверяет, есть ли пользователь в БД по username"""
    return is_user_allowed_by_username(username)

def is_admin_by_name(username):
    """Проверяет, является ли пользователь админом по username"""
    return is_admin_by_username(username)

def add_allowed_user(vk_id, username, added_by, note=""):
    """Добавляет пользователя в БД"""
    return add_user(vk_id, username, added_by, note)

def remove_allowed_user(username):
    """Удаляет пользователя по username"""
    return remove_user_by_username(username)

def list_all_users():
    """Возвращает список всех пользователей"""
    return get_all_users()

def get_username(user_id):
    """Получает username по VK ID"""
    return get_username_by_vk_id(user_id)

def is_attorney(vk_id):
    """Проверяет, является ли пользователь атторнеем по ID"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute('SELECT is_attorney FROM users WHERE vk_id = ?', (vk_id,))
    result = cursor.fetchone()

    conn.close()
    return result and result[0] == 1

def is_attorney_by_username(username):
    """Проверяет, является ли пользователь атторнеем по username"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    clean_username = username.lower().replace('@', '')
    cursor.execute('SELECT is_attorney FROM users WHERE LOWER(username) = ?', (clean_username,))
    result = cursor.fetchone()

    conn.close()
    return result and result[0] == 1

def is_leader(vk_id):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute('SELECT is_leader FROM users WHERE vk_id = ?', (vk_id,))
    result = cursor.fetchone()

    conn.close()
    return result and result[0] == 1

def is_judge(vk_id):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute('SELECT is_judge FROM users WHERE vk_id = ?', (vk_id,))
    result = cursor.fetchone()

    conn.close()
    return result and result[0] == 1


def get_all_judges():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute('''
        SELECT vk_id, username, added_date, last_used, note
        FROM users
        WHERE is_judge = 1
        ORDER BY added_date DESC
    ''')
    judges = cursor.fetchall()

    conn.close()
    return judges

def get_all_attorneys():
    """Возвращает список всех атторнеев"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute('''
        SELECT vk_id, username, added_date, last_used, note 
        FROM users 
        WHERE is_attorney = 1
        ORDER BY added_date DESC
    ''')
    attorneys = cursor.fetchall()

    conn.close()
    return attorneys

def get_all_leaders():
    """Возвращает список всех лидеров"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute('''
        SELECT vk_id, username, added_date, last_used, note
        FROM users
        WHERE is_leader = 1
        ORDER BY added_date DESC
    ''')
    leaders = cursor.fetchall()

    conn.close()
    return leaders

def save_role_chat(role, chat_id, registered_by=None):
    """Сохраняет или обновляет ID беседы для роли"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute('''
        INSERT OR REPLACE INTO role_chats (role, chat_id, registered_by, registered_at)
        VALUES (?, ?, ?, CURRENT_TIMESTAMP)
    ''', (role, chat_id, registered_by))

    conn.commit()
    conn.close()

def get_role_chat(role):
    """Получает ID беседы для роли"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute('SELECT chat_id FROM role_chats WHERE role = ?', (role,))
    result = cursor.fetchone()

    conn.close()
    return result[0] if result else None

def get_all_role_chats_with_names(vk_api):
    """Получает все зарегистрированные беседы с их названиями"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute('SELECT role, chat_id FROM role_chats')
    results = cursor.fetchall()

    conn.close()

    role_chats = []
    for role, chat_id in results:
        # Получаем название беседы через VK API
        chat_name = get_chat_name(vk_api, chat_id)
        role_chats.append({
            'role': role,
            'chat_id': chat_id,
            'chat_name': chat_name
        })

    return role_chats

def get_all_role_chats():
    """Получает все зарегистрированные беседы в виде словаря {role: chat_id}"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    # Проверяем, существует ли таблица
    cursor.execute("""
        SELECT name FROM sqlite_master 
        WHERE type='table' AND name='role_chats'
    """)

    if not cursor.fetchone():
        conn.close()
        return {}

    cursor.execute('SELECT role, chat_id FROM role_chats')
    results = cursor.fetchall()

    conn.close()
    return {role: chat_id for role, chat_id in results}

def get_chat_name(vk_api, peer_id):
    """Получает название беседы по peer_id"""
    try:
        # Для бесед peer_id начинается с 2000000000
        if peer_id >= 2000000000:
            chat_id = peer_id - 2000000000
            # Получаем информацию о беседе
            conversation = vk_api.messages.getConversationsById(peer_ids=peer_id)

            if conversation and conversation.get('items'):
                chat_info = conversation['items'][0]
                chat_name = chat_info.get('chat_settings', {}).get('title', 'Без названия')
                return chat_name
        return "Личные сообщения"
    except Exception as e:
        logger.error(f"Ошибка получения названия беседы {peer_id}: {e}")
        return "Неизвестная беседа"

def delete_role_chat(role):
    """Удаляет регистрацию беседы для роли"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute('DELETE FROM role_chats WHERE role = ?', (role,))
    conn.commit()
    conn.close()

def get_all_judge_chats():
    """Получает все беседы, где есть судьи (может быть несколько)"""
    # Если нужно поддерживать несколько бесед для одной роли
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute('SELECT chat_id FROM role_chats WHERE role = ?', ('judge',))
    results = cursor.fetchall()

    conn.close()
    return [row[0] for row in results]
