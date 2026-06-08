# State-LoveBot

VK-бот для администрирования игрового сервера Arizona RP.

## Архитектура (v2)

```text
project_root/
├── config/              # Конфигурация (env, логирование)
├── database/            # Tortoise ORM, модели, репозитории
│   ├── models/
│   └── repository/
├── middlewares/         # Проверка доступов, логирование
├── modules/             # Бизнес-модули
│   ├── administration/  # /kick, /pullkick
│   ├── profile/         # /setnick, /who, /get
│   └── pools/           # /regchat, /createpool, /pools
├── services/            # VK resolver, модерация, валидация ников
├── legacy/              # Старый forum-бот (vk-api, синхронный)
├── scripts/             # Миграция из users.db
└── main.py              # Точка входа (vkbottle, async)
```

## Быстрый старт

1. Скопируйте `.env.example` → `.env` и заполните переменные.
2. Установите зависимости:

```bash
pip install -r requirements.txt
```

3. (Опционально) Мигрируйте данные из старой БД:

```bash
python scripts/migrate_legacy_db.py
```

4. Запустите бота:

```bash
python main.py
```

## Уровни доступа

| Уровень | Роль | Ключевые команды |
|--------:|------|------------------|
| 1 | ПГС | `/get`, `/who`, `/setnick` |
| 2 | Следящий | `/kick` |
| 4 | ГС | `/pullkick` |
| 7 | Куратор | `/poolnotify` |
| 9 | ГА | `/regchat`, `/createpool`, `/setlevel` |
| 10 | Разраб | Глобальный доступ ко всем серверам |

Права привязаны к `server_id`. Уровень 10 действует на всех серверах.

## Legacy forum-бот

Функционал форума (`!info`, `/notif`, `/res` и т.д.) сохранён в `legacy/forum_bot.py`.
Для запуска старой версии:

```bash
python legacy/forum_bot.py
```

Требует модуль `arizona_forum_async` и настроенные cookies форума.

## Миграции Aerich

```bash
aerich init -t config.settings.TORTOISE_ORM
aerich init-db
aerich migrate
aerich upgrade
```

При первом запуске схема создаётся автоматически через `Tortoise.generate_schemas`.
