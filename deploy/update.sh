#!/usr/bin/env bash
# Обновление на сервере: sudo bash deploy/update.sh
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/State-LoveBot}"
APP_USER="${APP_USER:-lovebot}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/state-lovebot}"
TS="$(date +%Y%m%d-%H%M%S)"

cd "${APP_DIR}"
mkdir -p "${BACKUP_DIR}"

DB_FILES=(bot.db users.db)
DB_SIDE_FILES=(bot.db-wal bot.db-shm users.db-wal users.db-shm)

count_users() {
  local db="$1"
  [[ -f "${db}" ]] || { echo 0; return; }
  "${APP_DIR}/venv/bin/python" - "$db" <<'PY'
import sqlite3
import sys

con = sqlite3.connect(sys.argv[1])
try:
    print(con.execute("SELECT COUNT(*) FROM users").fetchone()[0])
except Exception:
    print(0)
finally:
    con.close()
PY
}

for db in "${DB_FILES[@]}"; do
  if [[ ! -f "${db}" ]]; then
    continue
  fi
  cp -a "${db}" "${BACKUP_DIR}/${db}.${TS}"
  ln -sfn "${BACKUP_DIR}/${db}.${TS}" "${BACKUP_DIR}/${db}.pre-update"
  if sudo -u "${APP_USER}" env HOME="${APP_DIR}" git -C "${APP_DIR}" ls-files --error-unmatch "${db}" &>/dev/null; then
    sudo -u "${APP_USER}" env HOME="${APP_DIR}" git -C "${APP_DIR}" update-index --skip-worktree "${db}" || true
  fi
  rm -f "${db}"
done
for extra in "${DB_SIDE_FILES[@]}"; do
  [[ -f "${extra}" ]] && rm -f "${extra}"
done

if [[ -d .git ]]; then
  sudo -u "${APP_USER}" env HOME="${APP_DIR}" git -C "${APP_DIR}" pull --ff-only
fi

for db in "${DB_FILES[@]}"; do
  backup="${BACKUP_DIR}/${db}.pre-update"
  if [[ ! -f "${backup}" ]]; then
    continue
  fi
  before="$(count_users "${backup}")"
  cp -a "${backup}" "${db}"
  chown "${APP_USER}:${APP_USER}" "${db}"
  after="$(count_users "${db}")"
  if [[ "${db}" == "bot.db" && "${before}" -gt 1 && "${after}" -le 1 ]]; then
    echo "ОШИБКА: bot.db после восстановления пустая (${after} users). Откат из ${backup}" >&2
    cp -a "${backup}" "${db}"
    chown "${APP_USER}:${APP_USER}" "${db}"
    exit 1
  fi
done

sudo -u "${APP_USER}" ./venv/bin/pip install -r requirements.txt
systemctl restart state-lovebot

echo "Обновлено. Бэкап: ${BACKUP_DIR}/bot.db.${TS}"
echo "Проверка: systemctl status state-lovebot"
