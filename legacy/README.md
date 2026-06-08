# Legacy forum-бот

Прежний синхронный бот на `vk-api` с интеграцией форума Arizona.

## Файлы

| Файл | Назначение |
|------|------------|
| `forum_bot.py` | Основной класс `ForumBot` (нужно восстановить из бэкапа) |
| `config_legacy.py` | Старый конфиг |
| `database_legacy.py` | Синхронный sqlite3 |
| `users_db.py` | Обёртки над БД |
| `logger.py` | Синхронный логгер |

> **Важно:** `forum_bot.py` не был в git. Скопируйте сюда ваш старый `main.py`, если он сохранился локально.

## Запуск

После восстановления `forum_bot.py` обновите импорты:

```python
from legacy.config_legacy import VK_GROUP_ID, ...
from legacy.database_legacy import init_db, DB_FILE
from legacy.users_db import is_user_allowed, ...
from legacy.logger import ActionLogger
```

Запуск из корня проекта:

```bash
python -m legacy.forum_bot
```

Требует модуль `arizona_forum_async` и cookies форума в `.env`.
