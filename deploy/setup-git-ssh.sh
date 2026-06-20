#!/usr/bin/env bash
# Настройка SSH для git pull от пользователя lovebot.
# Запуск на VPS: sudo bash deploy/setup-git-ssh.sh
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/State-LoveBot}"
APP_USER="${APP_USER:-lovebot}"
REPO_URL="${REPO_URL:-git@github.com:JakeMoralez/State-LoveBot.git}"
SSH_DIR="${APP_DIR}/.ssh"
KEY="${SSH_DIR}/id_ed25519"
CONFIG="${SSH_DIR}/config"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Запустите от root: sudo bash deploy/setup-git-ssh.sh"
  exit 1
fi

if ! id "${APP_USER}" &>/dev/null; then
  useradd --system --home "${APP_DIR}" --shell /usr/sbin/nologin "${APP_USER}"
fi

mkdir -p "${APP_DIR}" "${SSH_DIR}"
chown -R "${APP_USER}:${APP_USER}" "${APP_DIR}"

if [[ ! -f "${KEY}" ]]; then
  echo "==> Создаю SSH-ключ для ${APP_USER}"
  sudo -u "${APP_USER}" env HOME="${APP_DIR}" ssh-keygen -t ed25519 \
    -C "state-lovebot-vps" -f "${KEY}" -N ""
fi

install -m 700 -o "${APP_USER}" -g "${APP_USER}" -d "${SSH_DIR}"
chmod 600 "${KEY}"
chmod 644 "${KEY}.pub"
chown "${APP_USER}:${APP_USER}" "${KEY}" "${KEY}.pub"

cat >"${CONFIG}" <<EOF
Host github.com
  HostName github.com
  User git
  IdentityFile ${KEY}
  IdentitiesOnly yes
  StrictHostKeyChecking accept-new
EOF
chmod 600 "${CONFIG}"
chown "${APP_USER}:${APP_USER}" "${CONFIG}"

if [[ -d "${APP_DIR}/.git" ]]; then
  cd "${APP_DIR}"
  current="$(sudo -u "${APP_USER}" env HOME="${APP_DIR}" git remote get-url origin 2>/dev/null || true)"
  if [[ "${current}" != "${REPO_URL}" ]]; then
    echo "==> git remote origin -> ${REPO_URL}"
    sudo -u "${APP_USER}" env HOME="${APP_DIR}" git remote set-url origin "${REPO_URL}"
  fi
  sudo -u "${APP_USER}" env HOME="${APP_DIR}" git config --local safe.directory "${APP_DIR}"
fi

echo ""
echo "=== Публичный ключ (добавьте в GitHub → Settings → Deploy keys) ==="
cat "${KEY}.pub"
echo ""
echo "Репозиторий: https://github.com/JakeMoralez/State-LoveBot/settings/keys"
echo ""
echo "=== Проверка SSH ==="
if sudo -u "${APP_USER}" env HOME="${APP_DIR}" ssh -T git@github.com 2>&1 | tee /tmp/state-lovebot-ssh-test.log; then
  true
fi
if grep -qi "successfully authenticated\|You've successfully authenticated" /tmp/state-lovebot-ssh-test.log; then
  echo ""
  echo "OK: SSH к GitHub работает."
else
  echo ""
  echo "Ещё не OK: добавьте ключ выше в Deploy keys, затем снова:"
  echo "  sudo -u lovebot env HOME=${APP_DIR} ssh -T git@github.com"
fi
