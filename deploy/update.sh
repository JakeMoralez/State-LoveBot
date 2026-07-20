#!/usr/bin/env bash
# Обновление на сервере: sudo bash deploy/update.sh
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/State-LoveBot}"
APP_USER="${APP_USER:-lovebot}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/state-lovebot}"
TS="$(date +%Y%m%d-%H%M%S)"

cd "${APP_DIR}"

read_env_var() {
  local key="$1"
  local file="${APP_DIR}/.env"
  [[ -f "${file}" ]] || return 0
  # Берём последнее значение ключа; кавычки снимаем
  local line
  line="$(grep -E "^${key}=" "${file}" | tail -n1 || true)"
  [[ -n "${line}" ]] || return 0
  local val="${line#*=}"
  val="${val%\"}"
  val="${val#\"}"
  val="${val%\'}"
  val="${val#\'}"
  printf '%s' "${val}"
}

DATABASE_URL="$(read_env_var DATABASE_URL)"
IS_POSTGRES=0
case "${DATABASE_URL}" in
  postgres://*|postgresql://*) IS_POSTGRES=1 ;;
esac

# Опциональный бэкап Postgres перед обновлением (не трогаем старые .db)
if [[ "${IS_POSTGRES}" -eq 1 ]]; then
  mkdir -p "${BACKUP_DIR}"
  chown "${APP_USER}:${APP_USER}" "${BACKUP_DIR}" 2>/dev/null || true
  if command -v pg_dump >/dev/null 2>&1; then
    dump="${BACKUP_DIR}/state_love_bot.${TS}.sql.gz"
    echo "Бэкап Postgres → ${dump}"
    if sudo -u "${APP_USER}" pg_dump "${DATABASE_URL}" | gzip -c > "${dump}"; then
      chown "${APP_USER}:${APP_USER}" "${dump}" 2>/dev/null || true
      ln -sfn "${dump}" "${BACKUP_DIR}/state_love_bot.pre-update.sql.gz"
    else
      echo "Предупреждение: pg_dump не удался, обновление продолжаем" >&2
      rm -f "${dump}"
    fi
  else
    echo "Предупреждение: pg_dump не найден, бэкап БД пропущен" >&2
  fi
fi

if [[ -d .git ]]; then
  sudo -u "${APP_USER}" env HOME="${APP_DIR}" git -C "${APP_DIR}" pull --ff-only
fi

chown "${APP_USER}:${APP_USER}" "${APP_DIR}" 2>/dev/null || true
if [[ "${EUID}" -eq 0 ]]; then
  chown -R "${APP_USER}:${APP_USER}" "${APP_DIR}"
fi

sudo -u "${APP_USER}" ./venv/bin/pip install -r requirements.txt
systemctl restart state-lovebot

echo "Обновлено."
if [[ "${IS_POSTGRES}" -eq 1 ]]; then
  echo "БД: PostgreSQL (sqlite .db больше не трогаем)"
  if [[ -L "${BACKUP_DIR}/state_love_bot.pre-update.sql.gz" || -f "${BACKUP_DIR}/state_love_bot.pre-update.sql.gz" ]]; then
    echo "Бэкап: ${BACKUP_DIR}/state_love_bot.pre-update.sql.gz"
  fi
else
  echo "БД: ${DATABASE_URL:-не задана} — при SQLite бэкапьте .db вручную"
fi
echo "Проверка: systemctl status state-lovebot"
