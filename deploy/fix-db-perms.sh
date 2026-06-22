#!/usr/bin/env bash
# Восстановление bot.db (убрать симлинк в /var/backups) и прав.
# Запуск: sudo bash deploy/fix-db-perms.sh
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/State-LoveBot}"
APP_USER="${APP_USER:-lovebot}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/state-lovebot}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Запустите от root: sudo bash deploy/fix-db-perms.sh"
  exit 1
fi

systemctl stop state-lovebot 2>/dev/null || true

if [[ -L "${APP_DIR}/bot.db" ]]; then
  real="$(readlink -f "${APP_DIR}/bot.db")"
  echo "bot.db — симлинк на ${real}, копируем в ${APP_DIR}/bot.db"
  rm -f "${APP_DIR}/bot.db"
  cp -a "${real}" "${APP_DIR}/bot.db"
fi

chown -R "${APP_USER}:${APP_USER}" "${APP_DIR}"
chmod u+w "${APP_DIR}"
chown "${APP_USER}:${APP_USER}" "${BACKUP_DIR}" 2>/dev/null || true

rm -f "${APP_DIR}"/bot.db-wal "${APP_DIR}"/bot.db-shm

echo "=== bot.db ==="
ls -la "${APP_DIR}/bot.db"
namei -l "${APP_DIR}/bot.db" 2>/dev/null || true

sudo -u "${APP_USER}" bash -c "
  cd '${APP_DIR}'
  ./venv/bin/python -c \"
import sqlite3
c = sqlite3.connect('bot.db')
print('integrity:', c.execute('pragma integrity_check').fetchone()[0])
print('users:', c.execute('select count(*) from users').fetchone()[0])
c.execute('pragma journal_mode=WAL')
c.execute('create table if not exists _perm_test(x)')
c.execute('drop table _perm_test')
c.commit()
print('write: OK')
\"
"

systemctl start state-lovebot
sleep 2
tail -15 /var/log/state-lovebot/bot.log
