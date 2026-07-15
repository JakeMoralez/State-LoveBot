# Миграция SQLite → PostgreSQL (VPS)

Один инстанс PostgreSQL, две базы:

| База | Назначение |
|------|------------|
| `state_love_bot` | бот + staff из admin (`BOT_DATABASE_URL`) |
| `state_love_panel` | задачи, чеклист, discord_links (`PANEL_DATABASE_URL`) |

## 1. Бэкап SQLite

```bash
sudo systemctl stop state-lovebot state-love-admin
cp /opt/State-LoveBot/bot.db /opt/State-LoveBot/bot.db.bak.$(date +%F)
cp /opt/State-Love-Admin/data/panel.db /opt/State-Love-Admin/data/panel.db.bak.$(date +%F)
```

## 2. Запуск PostgreSQL (Docker)

```bash
cd /opt/State-LoveBot/deploy/postgres
cp .env.example .env
# отредактировать POSTGRES_PASSWORD
docker compose up -d
docker compose ps
```

Проверка:

```bash
docker exec -it state-love-postgres psql -U lovebot -d state_love_bot -c '\l'
```

## 3. Обновить .env

**`/opt/State-LoveBot/.env`:**

```env
DATABASE_URL=postgres://lovebot:PASSWORD@127.0.0.1:5432/state_love_bot
PANEL_DATABASE_URL=postgres://lovebot:PASSWORD@127.0.0.1:5432/state_love_panel
```

**`/opt/State-Love-Admin/.env`:**

```env
BOT_DATABASE_URL=postgres://lovebot:PASSWORD@127.0.0.1:5432/state_love_bot
PANEL_DATABASE_URL=postgres://lovebot:PASSWORD@127.0.0.1:5432/state_love_panel
```

`PASSWORD` — тот же, что `POSTGRES_PASSWORD` в `deploy/postgres/.env`.

## 4. Зависимости и миграция данных

```bash
cd /opt/State-LoveBot
source venv/bin/activate
pip install -r requirements.txt

python scripts/migrate_sqlite_to_postgres.py \
  --init-schemas \
  --bot-sqlite /opt/State-LoveBot/bot.db \
  --panel-sqlite /opt/State-Love-Admin/data/panel.db
```

Скрипт создаёт таблицы (Tortoise) и копирует все строки из SQLite.

## 5. Admin + бот

```bash
cd /opt/State-Love-Admin/backend
source ../venv/bin/activate   # или свой venv
pip install -r requirements.txt

sudo systemctl start state-love-admin state-lovebot
sudo systemctl status state-love-admin state-lovebot
curl -s http://127.0.0.1:8000/api/health | jq
```

Ожидается `"bot_db": "postgresql"`, `staff_count > 0`.

## 6. Проверки

```bash
# staff в PG
docker exec -it state-love-postgres psql -U lovebot -d state_love_bot \
  -c "SELECT COUNT(*) FROM users;"

# forum nick
docker exec -it state-love-postgres psql -U lovebot -d state_love_bot \
  -c "SELECT vk_id, username FROM users WHERE vk_id=604562391;"
```

Бот: `/ping`, `/me`, `/court`.

## Откат

1. Остановить сервисы
2. В `.env` вернуть `sqlite:////opt/State-LoveBot/bot.db` и `panel.db`
3. Запустить сервисы (бэкапы `.bak` на месте)

## Локальная разработка

Windows / локально — тот же `postgres://` URL или оставить SQLite:

```env
DATABASE_URL=sqlite://bot.db
PANEL_DATABASE_URL=sqlite://../State-LoveAdmin/data/panel.db
```

Код автоматически пропускает SQLite-only миграции (`ALTER TABLE`) при PostgreSQL.
