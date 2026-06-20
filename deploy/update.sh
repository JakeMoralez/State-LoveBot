#!/usr/bin/env bash
# Обновление на сервере: sudo bash deploy/update.sh
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/State-LoveBot}"
APP_USER="${APP_USER:-lovebot}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/state-lovebot}"

cd "${APP_DIR}"
mkdir -p "${BACKUP_DIR}"

# Боевую SQLite не трогаем — git pull не должен её перезаписывать
DB_FILES=(bot.db users.db)
for db in "${DB_FILES[@]}"; do
  if [[ ! -f "${db}" ]]; then
    continue
  fi
  cp -a "${db}" "${BACKUP_DIR}/${db}.pre-update"
  if sudo -u "${APP_USER}" git ls-files --error-unmatch "${db}" &>/dev/null; then
    sudo -u "${APP_USER}" git update-index --skip-worktree "${db}" || true
  fi
done

if [[ -d .git ]]; then
  sudo -u "${APP_USER}" git pull --ff-only
fi

for db in "${DB_FILES[@]}"; do
  if [[ -f "${BACKUP_DIR}/${db}.pre-update" ]]; then
    cp -a "${BACKUP_DIR}/${db}.pre-update" "${db}"
    chown "${APP_USER}:${APP_USER}" "${db}"
  fi
done

sudo -u "${APP_USER}" ./venv/bin/pip install -r requirements.txt
systemctl restart state-lovebot

echo "Обновлено. systemctl status state-lovebot"
