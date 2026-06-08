#!/usr/bin/env bash
# Обновление на сервере: sudo bash deploy/update.sh
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/State-LoveBot}"
APP_USER="${APP_USER:-lovebot}"

cd "${APP_DIR}"

if [[ -d .git ]]; then
  sudo -u "${APP_USER}" git pull --ff-only
fi

sudo -u "${APP_USER}" ./venv/bin/pip install -r requirements.txt
systemctl restart state-lovebot

echo "Обновлено. systemctl status state-lovebot"
