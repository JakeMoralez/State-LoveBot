#!/usr/bin/env python3
"""One-time migration: SQLite bot.db + panel.db → PostgreSQL.

Usage (on VPS after PostgreSQL is running and .env points to postgres URLs):

  cd /opt/State-LoveBot
  source venv/bin/activate
  pip install asyncpg
  python scripts/migrate_sqlite_to_postgres.py \\
    --bot-sqlite /opt/State-LoveBot/bot.db \\
    --panel-sqlite /opt/State-Love-Admin/data/panel.db \\
    --init-schemas

Environment (from .env):
  DATABASE_URL / BOT_DATABASE_URL — postgres URL for bot DB
  PANEL_DATABASE_URL — postgres URL for panel DB
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
load_dotenv(ROOT / ".env")

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("migrate")


def _pg_dsn(url: str) -> str:
    raw = (url or "").strip()
    if raw.startswith("postgres://"):
        return "postgresql://" + raw[len("postgres://") :]
    return raw


def sqlite_tables(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    return [r[0] for r in rows]


def sqlite_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]


def normalize_value(value: Any, pg_type: str) -> Any:
    if value is None:
        return None
    pg_type = (pg_type or "").lower()
    if pg_type == "boolean":
        return bool(value)
    if pg_type in ("json", "jsonb"):
        if isinstance(value, (dict, list)):
            return json.dumps(value)
        if isinstance(value, str):
            try:
                json.loads(value)
                return value
            except json.JSONDecodeError:
                return json.dumps(value)
    return value


async def pg_column_types(conn, table: str) -> dict[str, str]:
    rows = await conn.fetch(
        """
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = $1
        ORDER BY ordinal_position
        """,
        table,
    )
    return {r["column_name"]: r["data_type"] for r in rows}


async def pg_table_exists(conn, table: str) -> bool:
    return bool(
        await conn.fetchval(
            """
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = $1
            )
            """,
            table,
        )
    )


async def reset_sequences(conn, table: str) -> None:
    row = await conn.fetchrow(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = $1
          AND column_default LIKE 'nextval%%'
        LIMIT 1
        """,
        table,
    )
    if not row:
        return
    col = row["column_name"]
    seq = await conn.fetchval("SELECT pg_get_serial_sequence($1, $2)", table, col)
    if not seq:
        return
    max_id = await conn.fetchval(f'SELECT COALESCE(MAX("{col}"), 0) FROM "{table}"')
    await conn.execute("SELECT setval($1, $2, $3)", seq, max_id, max_id > 0)
    logger.info("  sequence %s → %s", seq, max_id)


async def copy_sqlite_to_postgres(
    sqlite_path: Path,
    pg_url: str,
    *,
    label: str,
) -> None:
    import asyncpg

    if not sqlite_path.is_file():
        raise FileNotFoundError(f"{label}: SQLite file not found: {sqlite_path}")

    dsn = _pg_dsn(pg_url)
    if not dsn.lower().startswith("postgresql://"):
        raise ValueError(f"{label}: expected postgres URL, got {pg_url!r}")

    sqlite_conn = sqlite3.connect(str(sqlite_path))
    pg_conn = await asyncpg.connect(dsn)

    try:
        tables = sqlite_tables(sqlite_conn)
        # Parents first so FK inserts work without session_replication_role.
        preferred = (
            "servers",
            "users",
            "user_server_access",
            "chats",
            "pools",
            "role_chats",
        )
        tables = sorted(
            tables,
            key=lambda t: (preferred.index(t) if t in preferred else 100, t),
        )
        logger.info("%s: %d tables in SQLite", label, len(tables))

        try:
            await pg_conn.execute("SET session_replication_role = replica")
            replication_role = True
        except Exception as exc:
            logger.warning(
                "  cannot set session_replication_role (%s) — inserting with FK checks",
                exc,
            )
            replication_role = False

        copied_total = 0
        for table in tables:
            if not await pg_table_exists(pg_conn, table):
                logger.warning("  skip %s (no table in PostgreSQL schema)", table)
                continue

            cols_sqlite = sqlite_columns(sqlite_conn, table)
            pg_types = await pg_column_types(pg_conn, table)
            cols = [c for c in cols_sqlite if c in pg_types]
            if not cols:
                logger.warning("  skip %s (no matching columns)", table)
                continue

            rows = sqlite_conn.execute(
                f'SELECT {", ".join(cols)} FROM "{table}"'
            ).fetchall()
            if not rows:
                logger.info("  %s: empty", table)
                continue

            await pg_conn.execute(f'TRUNCATE TABLE "{table}" RESTART IDENTITY CASCADE')

            col_list = ", ".join(f'"{c}"' for c in cols)
            placeholders = ", ".join(f"${i + 1}" for i in range(len(cols)))
            insert_sql = f'INSERT INTO "{table}" ({col_list}) VALUES ({placeholders})'

            batch: list[tuple[Any, ...]] = []
            for row in rows:
                values = tuple(
                    normalize_value(row[i], pg_types.get(cols[i], ""))
                    for i in range(len(cols))
                )
                batch.append(values)

            await pg_conn.executemany(insert_sql, batch)
            await reset_sequences(pg_conn, table)
            copied_total += len(batch)
            logger.info("  %s: %d rows", table, len(batch))

        if replication_role:
            await pg_conn.execute("SET session_replication_role = DEFAULT")
        logger.info("%s: done, %d rows total", label, copied_total)
    finally:
        sqlite_conn.close()
        await pg_conn.close()


async def init_bot_schema() -> None:
    from tortoise import Tortoise

    from config.settings import TORTOISE_ORM

    await Tortoise.init(config=TORTOISE_ORM)
    await Tortoise.generate_schemas(safe=True)
    await Tortoise.close_connections()
    logger.info("Bot PostgreSQL schema ready")


async def init_panel_schema() -> None:
    candidates = [
        Path("/opt/State-Love-Admin/backend"),
        ROOT.parent / "State-Love-Admin" / "backend",
        ROOT.parent / "State-LoveAdmin" / "backend",
    ]
    admin_root = next((p for p in candidates if p.is_dir()), None)
    if admin_root is None:
        logger.warning(
            "State-Love-Admin backend not found (tried %s) — skip panel schema init",
            ", ".join(str(p) for p in candidates),
        )
        return

    sys.path.insert(0, str(admin_root))
    from tortoise import Tortoise

    from app.config import TORTOISE_ORM

    await Tortoise.init(config=TORTOISE_ORM)
    await Tortoise.generate_schemas(safe=True)
    await Tortoise.close_connections()
    logger.info("Panel PostgreSQL schema ready (%s)", admin_root)


async def main_async(args: argparse.Namespace) -> None:
    bot_pg = (
        args.bot_postgres
        or os.getenv("DATABASE_URL")
        or os.getenv("BOT_DATABASE_URL", "")
    )
    panel_pg = args.panel_postgres or os.getenv("PANEL_DATABASE_URL", "")

    if args.init_schemas:
        if not bot_pg.lower().startswith(("postgres://", "postgresql://")):
            raise SystemExit(
                "DATABASE_URL must be postgres://... for --init-schemas "
                f"(got {bot_pg!r}). Update /opt/State-LoveBot/.env first."
            )
        await init_bot_schema()
        await init_panel_schema()

    if args.bot_sqlite:
        await copy_sqlite_to_postgres(Path(args.bot_sqlite), bot_pg, label="bot")

    if args.panel_sqlite:
        await copy_sqlite_to_postgres(
            Path(args.panel_sqlite), panel_pg, label="panel"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate SQLite → PostgreSQL")
    parser.add_argument(
        "--bot-sqlite",
        help="Path to bot.db (source)",
    )
    parser.add_argument(
        "--panel-sqlite",
        help="Path to panel.db (source)",
    )
    parser.add_argument(
        "--bot-postgres",
        help="Override target bot postgres URL (else DATABASE_URL from .env)",
    )
    parser.add_argument(
        "--panel-postgres",
        help="Override target panel postgres URL (else PANEL_DATABASE_URL)",
    )
    parser.add_argument(
        "--init-schemas",
        action="store_true",
        help="Create empty PostgreSQL tables from Tortoise models",
    )
    args = parser.parse_args()

    if not args.init_schemas and not args.bot_sqlite and not args.panel_sqlite:
        parser.error("Specify --init-schemas and/or --bot-sqlite / --panel-sqlite")

    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
