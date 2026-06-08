#!/usr/bin/env bash
# Установка State-LoveBot на Linux (VPS). Запуск: sudo bash deploy/install.sh
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/State-LoveBot}"
APP_USER="${APP_USER:-lovebot}"
REPO_URL="${REPO_URL:-}"

echo "==> State-LoveBot install -> ${APP_DIR}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Запустите от root: sudo bash deploy/install.sh"
  exit 1
fi

apt-get update -qq
apt-get install -y -qq git python3 python3-venv python3-pip

if ! id "${APP_USER}" &>/dev/null; then
  useradd --system --home "${APP_DIR}" --shell /usr/sbin/nologin "${APP_USER}"
fi

mkdir -p "${APP_DIR}" /var/log/state-lovebot
chown -R "${APP_USER}:${APP_USER}" /var/log/state-lovebot

if [[ -n "${REPO_URL}" && ! -d "${APP_DIR}/.git" ]]; then
  git clone "${REPO_URL}" "${APP_DIR}"
fi

if [[ ! -f "${APP_DIR}/main.py" ]]; then
  echo "Скопируйте проект в ${APP_DIR} или задайте REPO_URL=..."
  exit 1
fi

cd "${APP_DIR}"
chown -R "${APP_USER}:${APP_USER}" "${APP_DIR}"

sudo -u "${APP_USER}" python3 -m venv venv
sudo -u "${APP_USER}" ./venv/bin/pip install --upgrade pip
sudo -u "${APP_USER}" ./venv/bin/pip install -r requirements.txt

if [[ ! -f "${APP_DIR}/.env" ]]; then
  cp .env.example .env
  chown "${APP_USER}:${APP_USER}" .env
  echo ""
  echo "!!! Заполните ${APP_DIR}/.env и перезапустите: systemctl restart state-lovebot"
fi

install -m 644 deploy/state-lovebot.service /etc/systemd/system/state-lovebot.service
systemctl daemon-reload
systemctl enable state-lovebot
systemctl restart state-lovebot

echo ""
echo "Готово. Статус: systemctl status state-lovebot"
echo "Логи:     journalctl -u state-lovebot -f"
echo "           tail -f /var/log/state-lovebot/bot.log"
