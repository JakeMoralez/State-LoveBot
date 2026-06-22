#!/usr/bin/env bash
# Проверка целостности SQLite (bot.db, users.db).
# Запуск на VPS: sudo -u lovebot bash deploy/check-db.sh
# или: sudo bash deploy/check-db.sh  (от root, проверка от lovebot)
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/State-LoveBot}"
APP_USER="${APP_USER:-lovebot}"
DB="${1:-${APP_DIR}/bot.db}"

run_check() {
  local db="$1"
  sudo -u "${APP_USER}" "${APP_DIR}/venv/bin/python" - "$db" <<'PY'
import sqlite3
import sys
from pathlib import Path

db = Path(sys.argv[1])
print(f"=== {db} ===")
if db.is_symlink():
    print("ОШИБКА: это симлинк ->", db.resolve())
    print("Замените на обычный файл: sudo bash deploy/fix-db-perms.sh")
    sys.exit(2)
if not db.is_file():
    print("ОШИБКА: файл не найден")
    sys.exit(1)

con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
try:
    integrity = con.execute("pragma integrity_check").fetchone()[0]
    quick = con.execute("pragma quick_check").fetchone()[0]
    print("integrity_check:", integrity)
    print("quick_check:    ", quick)

    fk = con.execute("pragma foreign_key_check").fetchall()
    if fk:
        print("foreign_key_check: FAIL", len(fk), "ошибок")
        for row in fk[:10]:
            print(" ", row)
    else:
        print("foreign_key_check: ok")

    tables = [
        r[0]
        for r in con.execute(
            "select name from sqlite_master where type='table' order by name"
        ).fetchall()
    ]
    print("tables:", len(tables))

    for name in ("users", "servers", "forum_roles", "judge_forum_list_settings"):
        if name in tables:
            n = con.execute(f"select count(*) from {name}").fetchone()[0]
            print(f"  {name}: {n}")

    page_count = con.execute("pragma page_count").fetchone()[0]
    page_size = con.execute("pragma page_size").fetchone()[0]
    print(f"size: {db.stat().st_size} bytes, pages: {page_count} x {page_size}")

    if integrity != "ok" or quick != "ok":
        sys.exit(1)
    print("OK")
finally:
    con.close()
PY
}

cd "${APP_DIR}"

if [[ "${EUID}" -eq 0 ]]; then
  :
else
  APP_USER="$(whoami)"
fi

run_check "${DB}"

if [[ "${DB}" == *bot.db* && -f "${APP_DIR}/users.db" ]]; then
  echo ""
  run_check "${APP_DIR}/users.db"
fi
