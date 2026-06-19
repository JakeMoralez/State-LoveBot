#!/usr/bin/env bash
# Безопасная миграция с ручной установки на git + systemd.
# Запуск на сервере из старой папки бота:
#   sudo bash deploy/migrate-from-manual.sh
#
# Или:
#   sudo OLD_DIR=/root/State-LoveBot bash /path/to/migrate-from-manual.sh
set -euo pipefail

OLD_DIR="${OLD_DIR:-/root/State-LoveBot}"
NEW_DIR="${NEW_DIR:-/opt/State-LoveBot}"
APP_USER="${APP_USER:-lovebot}"
REPO_URL="${REPO_URL:-git@github.com:JakeMoralez/State-LoveBot.git}"
BACKUP_DIR="/var/backups/state-lovebot-$(date +%Y%m%d-%H%M%S)"

echo "==> Миграция State-LoveBot"
echo "    FROM: ${OLD_DIR}"
echo "    TO:   ${NEW_DIR}"
echo "    BACKUP: ${BACKUP_DIR}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Запустите от root: sudo bash deploy/migrate-from-manual.sh"
  exit 1
fi

if [[ ! -d "${OLD_DIR}" ]]; then
  echo "Старая папка не найдена: ${OLD_DIR}"
  echo "Задайте OLD_DIR=/path/to/old/bot"
  exit 1
fi

if pgrep -f "python.*main.py" >/dev/null 2>&1; then
  echo ""
  echo "!!! Обнаружен запущенный бот (python main.py)."
  echo "    Остановите его перед миграцией:"
  echo "      sudo systemctl stop state-lovebot"
  echo "    или завершите screen/tmux вручную."
  read -r -p "Продолжить всё равно? [y/N] " ans
  [[ "${ans,,}" == "y" ]] || exit 1
fi

systemctl stop state-lovebot 2>/dev/null || true
sleep 2

mkdir -p "${BACKUP_DIR}"
echo "==> Бэкап .env и базы"

if [[ -f "${OLD_DIR}/.env" ]]; then
  cp -a "${OLD_DIR}/.env" "${BACKUP_DIR}/.env"
else
  echo "WARN: ${OLD_DIR}/.env не найден"
fi

for db in bot.db users.db; do
  if [[ -f "${OLD_DIR}/${db}" ]]; then
    cp -a "${OLD_DIR}/${db}" "${BACKUP_DIR}/${db}"
    echo "    saved ${db}"
  fi
done

# WAL/SHM рядом с sqlite
for extra in bot.db-wal bot.db-shm users.db-wal users.db-shm; do
  [[ -f "${OLD_DIR}/${extra}" ]] && cp -a "${OLD_DIR}/${extra}" "${BACKUP_DIR}/${extra}"
done

apt-get update -qq
apt-get install -y -qq git python3 python3-venv python3-pip

if ! id "${APP_USER}" &>/dev/null; then
  useradd --system --home "${NEW_DIR}" --shell /usr/sbin/nologin "${APP_USER}"
fi

mkdir -p "${NEW_DIR}" /var/log/state-lovebot
chown -R "${APP_USER}:${APP_USER}" /var/log/state-lovebot

if [[ -d "${NEW_DIR}/.git" ]]; then
  echo "==> ${NEW_DIR} уже git — git pull"
  cd "${NEW_DIR}"
  sudo -u "${APP_USER}" git pull --ff-only
else
  if [[ -f "${NEW_DIR}/main.py" ]]; then
    echo "ERROR: ${NEW_DIR} существует, но не git. Уберите или задайте другой NEW_DIR."
    exit 1
  fi
  echo "==> git clone -> ${NEW_DIR}"
  sudo -u "${APP_USER}" git clone "${REPO_URL}" "${NEW_DIR}"
fi

cd "${NEW_DIR}"

echo "==> Восстановление .env"
if [[ -f "${BACKUP_DIR}/.env" ]]; then
  cp -a "${BACKUP_DIR}/.env" "${NEW_DIR}/.env"
else
  if [[ ! -f "${NEW_DIR}/.env" ]]; then
    cp .env.example .env
    echo "!!! Создан пустой .env из example — заполните секреты!"
  fi
fi

# Определить имя файла БД из .env или по умолчанию bot.db
DB_FILE="bot.db"
if [[ -f "${NEW_DIR}/.env" ]]; then
  db_url="$(grep -E '^DATABASE_URL=' "${NEW_DIR}/.env" | head -1 | cut -d= -f2- || true)"
  if [[ "${db_url}" == sqlite://* ]]; then
    DB_FILE="$(basename "${db_url#sqlite://}")"
  fi
fi

echo "==> Восстановление базы (${DB_FILE})"
if [[ -f "${BACKUP_DIR}/${DB_FILE}" ]]; then
  cp -a "${BACKUP_DIR}/${DB_FILE}" "${NEW_DIR}/${DB_FILE}"
  for suffix in -wal -shm; do
    [[ -f "${BACKUP_DIR}/${DB_FILE}${suffix}" ]] && \
      cp -a "${BACKUP_DIR}/${DB_FILE}${suffix}" "${NEW_DIR}/${DB_FILE}${suffix}"
  done
elif [[ -f "${BACKUP_DIR}/bot.db" ]]; then
  cp -a "${BACKUP_DIR}/bot.db" "${NEW_DIR}/bot.db"
  DB_FILE="bot.db"
elif [[ -f "${BACKUP_DIR}/users.db" ]]; then
  cp -a "${BACKUP_DIR}/users.db" "${NEW_DIR}/users.db"
  DB_FILE="users.db"
else
  echo "WARN: файл базы не найден в бэкапе — будет новая БД"
fi

chown -R "${APP_USER}:${APP_USER}" "${NEW_DIR}"

echo "==> Python venv"
if [[ ! -d "${NEW_DIR}/venv" ]]; then
  sudo -u "${APP_USER}" python3 -m venv "${NEW_DIR}/venv"
fi
sudo -u "${APP_USER}" "${NEW_DIR}/venv/bin/pip" install --upgrade pip -q
sudo -u "${APP_USER}" "${NEW_DIR}/venv/bin/pip" install -r "${NEW_DIR}/requirements.txt" -q

# Добавить PANEL_BASE_URL если нет (для /panel)
if [[ -f "${NEW_DIR}/.env" ]] && ! grep -q '^PANEL_BASE_URL=' "${NEW_DIR}/.env"; then
  echo "" >> "${NEW_DIR}/.env"
  echo "PANEL_BASE_URL=https://love.vlesnix.site" >> "${NEW_DIR}/.env"
  echo "    добавлен PANEL_BASE_URL в .env"
fi

install -m 644 "${NEW_DIR}/deploy/state-lovebot.service" /etc/systemd/system/state-lovebot.service
systemctl daemon-reload
systemctl enable state-lovebot
systemctl restart state-lovebot

sleep 3
if systemctl is-active --quiet state-lovebot; then
  echo ""
  echo "✅ Бот запущен: systemctl status state-lovebot"
else
  echo ""
  echo "❌ Бот не стартовал. Смотрите:"
  echo "   journalctl -u state-lovebot -n 50 --no-pager"
  echo "   tail -50 /var/log/state-lovebot/bot.log"
  echo ""
  echo "Бэкап: ${BACKUP_DIR}"
  exit 1
fi

echo ""
echo "=========================================="
echo "Готово. Старая папка НЕ удалена: ${OLD_DIR}"
echo ""
echo "Обновите панель (/opt/State-Love-Admin/.env):"
echo "  BOT_DATABASE_URL=sqlite:////${NEW_DIR}/${DB_FILE}"
echo ""
echo "Проверьте в .env бота:"
echo "  PANEL_BASE_URL=https://love.vlesnix.site"
echo "  SLED_BOT_SECRET=<как в панели>"
echo ""
echo "  sudo systemctl restart state-love-admin"
echo ""
echo "Обновления бота дальше:"
echo "  cd ${NEW_DIR} && sudo bash deploy/update.sh"
echo "=========================================="
