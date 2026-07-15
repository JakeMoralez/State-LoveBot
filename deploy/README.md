# Deploy State-LoveBot (VPS)

Панель (`State-LoveAdmin`) уже в `/opt/State-Love-Admin` через git. Бот ставим так же — в `/opt/State-LoveBot`, чтобы обновляться одной командой и не трогать `/root`.

**Репозиторий приватный** — на VPS нужен SSH-ключ (см. раздел ниже).

---

## SSH для приватного GitHub (один раз)

`git pull` на сервере идёт от пользователя **`lovebot`**. Ключ нужен ему, не root.

**Быстрая настройка (рекомендуется):**

```bash
cd /opt/State-LoveBot
sudo bash deploy/setup-git-ssh.sh
```

Скрипт создаст `/opt/State-LoveBot/.ssh/config`, ключ `id_ed25519`, покажет `.pub` для GitHub и проверит `ssh -T git@github.com`.

### Вручную

```bash
sudo mkdir -p /opt/State-LoveBot
sudo useradd --system --home /opt/State-LoveBot --shell /usr/sbin/nologin lovebot 2>/dev/null || true

sudo -u lovebot ssh-keygen -t ed25519 -C "state-lovebot-vps" -f /opt/State-LoveBot/.ssh/id_ed25519 -N ""
sudo -u lovebot chmod 700 /opt/State-LoveBot/.ssh
sudo -u lovebot chmod 600 /opt/State-LoveBot/.ssh/id_ed25519
```

Показать **публичный** ключ (его можно копировать — это не секрет):

```bash
sudo cat /opt/State-LoveBot/.ssh/id_ed25519.pub
```

### 2. Deploy Key в GitHub

1. Откройте https://github.com/JakeMoralez/State-LoveBot  
2. **Settings → Deploy keys → Add deploy key**  
3. Title: `VPS state-lovebot`  
4. Key: вставьте содержимое `id_ed25519.pub`  
5. **Allow write access** — **не включать** (только чтение)

### 3. Проверка

```bash
sudo -u lovebot ssh -o StrictHostKeyChecking=accept-new -T git@github.com
# ожидается: Hi JakeMoralez/State-LoveBot! You've successfully authenticated...
```

Если `Permission denied` — ключ не добавлен или добавлен не в тот репозиторий.

### 4. URL репозитория

Используйте SSH, не HTTPS:

```text
git@github.com:JakeMoralez/State-LoveBot.git
```

Скрипты `install.sh` / `migrate-from-manual.sh` уже с этим URL по умолчанию.

### Альтернатива: ваш личный ключ

Если клоните **от root** под своим аккаунтом GitHub — ключ root/home, не lovebot. Тогда `update.sh` всё равно делает `sudo -u lovebot git pull` — **лучше deploy key для lovebot**, как выше.

---

## Быстрое обновление (уже на git)

```bash
cd /opt/State-LoveBot
sudo bash deploy/update.sh
```

Или вручную:

```bash
cd /opt/State-LoveBot
sudo -u lovebot git pull --ff-only
sudo -u lovebot ./venv/bin/pip install -r requirements.txt
sudo systemctl restart state-lovebot
sudo systemctl status state-lovebot
```

---

## Миграция с ручной установки (без падения)

Если бот сейчас в `/root/State-LoveBot` или запускается вручную (`screen`, `nohup`) — **не удаляйте старую папку**, пока новый бот не заработает.

### Шаг 0 — на своём ПК

Закоммитьте и запушьте изменения в оба репо (`State-LoveBot`, `State-LoveAdmin`), иначе на сервере `git pull` не подтянет `/panel` и вход через бота.

### Шаг 1 — на VPS: остановить старый бот

```bash
# если был systemd под другим именем — остановите его
sudo systemctl stop state-lovebot 2>/dev/null || true

# если запускали в screen/tmux — зайдите и остановите (Ctrl+C)
# проверка, что процесс не висит:
pgrep -af "python.*main.py" || echo "бот не запущен — ок"
```

### Шаг 2 — миграция одним скриптом

```bash
cd /root/State-LoveBot   # или где сейчас лежит бот
sudo bash deploy/migrate-from-manual.sh
```

Скрипт:
- делает бэкап `.env` и `bot.db` в `/var/backups/state-lovebot-...`
- клонирует репо в `/opt/State-LoveBot` (если ещё нет)
- переносит `.env` и базу
- создаёт venv, ставит зависимости
- ставит `systemd` unit `state-lovebot`
- **не удаляет** `/root/State-LoveBot`

Переменные (если пути другие):

```bash
sudo OLD_DIR=/root/State-LoveBot \
     NEW_DIR=/opt/State-LoveBot \
     REPO_URL=git@github.com:JakeMoralez/State-LoveBot.git \
     bash deploy/migrate-from-manual.sh
```

### Шаг 3 — поправить панель (путь к БД бота)

После переноса база будет в `/opt/State-LoveBot/bot.db`. В `/opt/State-Love-Admin/.env`:

```env
BOT_DATABASE_URL=sqlite:////opt/State-LoveBot/bot.db
```

И в `.env` бота добавьте (для `/panel`):

```env
PANEL_BASE_URL=https://love.vlesnix.site
# SLED_BOT_SECRET — тот же, что в панели
```

Перезапуск панели:

```bash
sudo systemctl restart state-love-admin
```

### Шаг 4 — проверка

```bash
sudo systemctl status state-lovebot
journalctl -u state-lovebot -n 30 --no-pager
tail -20 /var/log/state-lovebot/bot.log

# internal API (для уведомлений панели)
curl -s -o /dev/null -w "%{http_code}\n" \
  -H "X-Sled-Secret: ВАШ_СЕКРЕТ" \
  http://127.0.0.1:8081/internal/staff-ca
# ожидается 200
```

В VK: `/ping`, затем `/panel` в ЛС (если есть доступ ЦА).

### Шаг 5 — когда всё стабильно (через 1–2 дня)

Старую папку можно переименовать, **не удаляя**:

```bash
sudo mv /root/State-LoveBot /root/State-LoveBot.old-manual
```

---

## Свежая установка (без миграции)

```bash
sudo REPO_URL=git@github.com:JakeMoralez/State-LoveBot.git bash deploy/install.sh
# заполнить /opt/State-LoveBot/.env
sudo systemctl restart state-lovebot
```

---

## Что в `.env` бота на проде

| Переменная | Зачем |
|------------|--------|
| `VK_GROUP_TOKEN`, `VK_GROUP_ID` | VK API |
| `DATABASE_URL=sqlite:////opt/State-LoveBot/bot.db` | база (тот же путь, что `BOT_DATABASE_URL` в панели) |
| `SLED_BOT_SECRET` | internal API + ссылки `/panel` (как в панели) |
| `PANEL_BASE_URL` | ссылки входа `/panel` |
| `SLED_INTERNAL_PORT=8081` | порт internal API |

---

## Откат

```bash
sudo systemctl stop state-lovebot
cd /root/State-LoveBot.old-manual   # или OLD_DIR
# запустить как раньше (screen / systemd)
# в панели вернуть BOT_DATABASE_URL=sqlite:////root/State-LoveBot/bot.db
sudo systemctl restart state-love-admin
```

Бэкапы: `/var/backups/state-lovebot-*`.
