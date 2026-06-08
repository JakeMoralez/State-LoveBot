# database.py
import sqlite3
import json
import os
import logging
from datetime import datetime

# Создаем логгер для этого модуля
logger = logging.getLogger(__name__)

DB_FILE = "users.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    # Таблица пользователей
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            vk_id INTEGER PRIMARY KEY,
            username TEXT,
            added_by INTEGER,
            added_date TEXT,
            last_used TEXT,
            is_admin INTEGER DEFAULT 0,
            is_judge INTEGER DEFAULT 0,
            is_attorney INTEGER DEFAULT 0,
            is_leader INTEGER DEFAULT 0,
            note TEXT
        )
    ''')

    # Таблица для хранения повесток
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
            reject_reason TEXT,
            processed_by_peer_id INTEGER
        )
    ''')

    # Таблица для хранения ID бесед ролей
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS role_chats (
            role TEXT PRIMARY KEY,
            chat_id INTEGER NOT NULL,
            registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            registered_by INTEGER
        )
    ''')

    # Добавляем главного админа из .env (если указан)
    from config import MAIN_ADMIN_ID, MAIN_ADMIN_USERNAME
    if MAIN_ADMIN_ID:
        cursor.execute('''
            INSERT OR IGNORE INTO users (vk_id, username, added_by, added_date, is_admin)
            VALUES (?, ?, ?, ?, ?)
        ''', (MAIN_ADMIN_ID, MAIN_ADMIN_USERNAME, 0, datetime.now().isoformat(), 1))

    conn.commit()
    conn.close()

def get_vk_id_by_username(username):
    """Получает VK ID по username (из базы или через API)"""
    # Сначала ищем в базе
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    # Убираем @ если есть
    clean_username = username.lower().replace('@', '')

    cursor.execute('SELECT vk_id FROM usaers WHERE username = ?', (clean_username,))
    result = cursor.fetchone()
    conn.close()

    if result:
        return result[0]

    # Если не нашли в базе, возвращаем None (позже можно добавить поиск через API)
    return None

def add_user(vk_id, username, added_by, note=""):
    """Добавляет пользователя в БД"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    # Проверяем, существует ли пользователь
    cursor.execute('SELECT vk_id FROM users WHERE vk_id = ?', (vk_id,))
    exists = cursor.fetchone()

    if exists:
        # Обновляем существующего
        cursor.execute('''
            UPDATE users 
            SET username = ?, note = ?, last_used = ?
            WHERE vk_id = ?
        ''', (username, note, datetime.now().isoformat(), vk_id))
    else:
        # Добавляем нового
        cursor.execute('''
            INSERT INTO users (vk_id, username, added_by, added_date, last_used, note, is_admin)
            VALUES (?, ?, ?, ?, ?, ?, 0)
        ''', (vk_id, username, added_by, datetime.now().isoformat(), 
              datetime.now().isoformat(), note))

    conn.commit()
    conn.close()
    logger.info(f"Пользователь {username} (id{vk_id}) добавлен/обновлен")
    return True

def remove_user_by_username(username):
    """Удаляет пользователя по username"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    clean_username = username.lower().replace('@', '')
    cursor.execute('DELETE FROM users WHERE username = ?', (clean_username,))
    deleted = cursor.rowcount > 0

    conn.commit()
    conn.close()
    return deleted

def is_user_allowed_by_username(username):
    """Проверяет, есть ли пользователь в БД по username"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    clean_username = username.lower().replace('@', '')
    cursor.execute('SELECT vk_id FROM users WHERE username = ?', (clean_username,))
    result = cursor.fetchone() is not None

    conn.close()
    return result

def is_admin_by_username(username):
    """Проверяет, является ли пользователь админом по username"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    clean_username = username.lower().replace('@', '')
    cursor.execute('SELECT is_admin FROM users WHERE username = ?', (clean_username,))
    result = cursor.fetchone()

    conn.close()
    return result and result[0] == 1

def get_all_users():
    """Возвращает список всех пользователей"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute('''
        SELECT vk_id, username, added_date, last_used, note, is_admin, is_attorney 
        FROM users 
        ORDER BY added_date DESC
    ''')
    users = cursor.fetchall()

    conn.close()
    return users

def get_all_roles(user_id):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT is_admin, is_judge, is_attorney, is_leader
        FROM users
        WHERE vk_id = ?
    """, (user_id,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        return []

    roles = []
    if row[0] == 1:
        roles.append("admin")
    if row[1] == 1:
        roles.append("judge")
    if row[2] == 1:
        roles.append("attorney")
    if row[3] == 1:
        roles.append("leader")

    return roles


def remove_all_roles(user_id):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE users
        SET is_admin = 0,
            is_judge = 0,
            is_attorney = 0,
            is_leader = 0
        WHERE vk_id = ?
    """, (user_id,))

    conn.commit()
    conn.close()


def update_note_by_username(username, note):
    """Обновляет заметку о пользователе по username"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    clean_username = username.lower().replace('@', '')
    cursor.execute('UPDATE users SET note = ? WHERE username = ?', (note, clean_username))

    conn.commit()
    conn.close()
    return cursor.rowcount > 0

def get_username_by_vk_id(vk_id):
    """Получает username по VK ID"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute('SELECT username FROM users WHERE vk_id = ?', (vk_id,))
    result = cursor.fetchone()

    conn.close()
    return result[0] if result else None

def is_user_allowed(vk_id):
    """Проверяет, есть ли пользователь в БД по его ID"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute('SELECT vk_id FROM users WHERE vk_id = ?', (vk_id,))
    result = cursor.fetchone() is not None

    conn.close()
    return result

def is_admin(vk_id):
    """Проверяет, является ли пользователь админом по ID"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute('SELECT is_admin FROM users WHERE vk_id = ?', (vk_id,))
    result = cursor.fetchone()

    conn.close()
    return result and result[0] == 1

def get_vk_id_by_username(username):
    """Возвращает VK ID пользователя по его username"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    clean_username = username.lower().replace('@', '')
    cursor.execute('SELECT vk_id FROM users WHERE LOWER(username) = ?', (clean_username,))
    result = cursor.fetchone()

    conn.close()
    return result[0] if result else None

def get_user_role(user_id):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute("SELECT role FROM roles WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    return row[0] if row else None

def remove_role(user_id):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute("DELETE FROM roles WHERE user_id = ?", (user_id,))
    conn.commit()

# Инициализация всех таблиц при импорте модуля
if __name__ != "__main__":
    init_db()
