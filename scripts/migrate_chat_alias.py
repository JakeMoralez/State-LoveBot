"""
Добавляет колонку alias в таблицу chats (если ещё нет).

python scripts/migrate_chat_alias.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


async def migrate() -> None:
    from tortoise import Tortoise

    from config import TORTOISE_ORM
    from database.connection import close_db, init_db

    await init_db()
    conn = Tortoise.get_connection("default")

    try:
        await conn.execute_query("ALTER TABLE chats ADD COLUMN alias VARCHAR(64) NULL")
        print("Колонка alias добавлена.")
    except Exception as exc:
        if "duplicate column" in str(exc).lower() or "already exists" in str(exc).lower():
            print("Колонка alias уже существует.")
        else:
            print(f"ALTER пропущен ({exc}), generate_schemas мог уже применить схему.")

    try:
        await conn.execute_query(
            "CREATE UNIQUE INDEX IF NOT EXISTS uid_chats_server_id_alias "
            "ON chats (server_id, alias) WHERE alias IS NOT NULL"
        )
        print("Индекс server_id+alias готов.")
    except Exception as exc:
        print(f"Индекс: {exc}")

    await close_db()
    print("Миграция завершена.")


if __name__ == "__main__":
    asyncio.run(migrate())
