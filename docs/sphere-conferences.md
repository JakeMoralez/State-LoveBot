# Сферные конференции: ревью и план

**Статус:** черновик спецификации (только документ, без кода)  
**Дата:** июнь 2026  
**Связанные документы:** [ROADMAP.md](../ROADMAP.md) (фаза 5), реализованный слой ЦА (`/setca`, `/regrole sledca`)

---

## 1. Цель

Дать возможность **привязывать VK-беседы к организационным ролям внутри сфер** и управлять доступом предсказуемо:

| Пример | Смысл |
|--------|--------|
| **РУК ЦА** | руководитель Центральной администрации — своя беседа, свои права выдачи |
| **РУК ГОС** | руководитель правительственного блока (ур. 5–6, пулы ГОС) |
| **Лидер ЦЛ** | руководитель Центра лицензирования (подструктура, чаще под ЦА или «Прочие») |
| **Лидер FBI / LSPD** | лидер фракции внутри сферы МЮ |

Сейчас бот умеет **частично** то же для ЦА (`has_ca_access`, беседа след. ЦА), суда, конгресса. Нет общей модели «сфера → должность → беседа → кто может назначать».

---

## 2. Ревью текущей архитектуры (as-is)

### 2.1. Три оси власти (уже описаны в ROADMAP)

```text
Уровень 1–10 (UserServerAccess)     → /kick, /setlevel, /createpool…
Форумные флаги (User)               → is_judge, is_leader, is_admin…
Привязка бесед (role_chats)         → одна запись на тип роли
Пулы (Pool + Chat)                  → массовые /msg, без сферы
```

Оси **не связаны** между собой на уровне БД: нельзя выразить «ЗГС **МЮ**» или «лидер **ЦЛ**» без доработки схемы.

### 2.2. Что уже работает в v2 (эталон для сфер)

| Паттерн | Реализация | Поведение при входе/выходе |
|---------|------------|----------------------------|
| Доступ ЦА (флаг) | `UserServerAccess.has_ca_access`, `/setca` | Ручная выдача; не привязан к беседе |
| Беседа след. ЦА | `ForumRoleKey.SLED_CA`, `/regrole sledca` | Вход → ур. 1 + `has_ca_access`; выход → снятие (`ca_auto_peer_id`) |
| Беседа судей | `ForumRoleKey.JUDGE`, `/regrole court` | Выход → `is_judge = false` |
| Конгресс | `ForumRoleKey.CONGRESS` + `CongressRepository` | Выход → снятие спикера/вице; `/setspeaker`, `/setvice` |
| Ограничение ЦА для ур. 1–4 | `requires_ca_scope` | Ур. 5+ без флага ЦА |

**Вывод:** паттерн `sled_ca` — лучший шаблон для сферных конф с **автовыдачей при входе**. Паттерн `congress` — для конф с **ручным назначением** должности и особыми правами внутри беседы.

### 2.3. Критические ограничения кода

#### A. Одна беседа на тип роли

`RoleChat.role` — **первичный ключ**. В БД может существовать только одна беседа на `judge`, `leader`, `sled_ca` и т.д.

```19:32:database/models/role_chat.py
class RoleChat(Model):
    role = fields.CharField(max_length=32, pk=True)
    peer_id = fields.BigIntField()
    ...
```

Для сфер нужно **много** бесед одного «типа» (лидер МЮ FBI, лидер МЮ LSPD, лидер ЦЛ, РУК ГОС…). Текущая модель это не поддерживает.

#### B. Глобальные boolean-флаги на `User`

`is_leader`, `is_admin`, `is_attorney` — **без привязки к сфере и подразделению**. Один человек не может быть одновременно «лидер ЦЛ» и «лидер SWAT» с раздельным автоснятием при выходе из разных бесед.

#### C. Legacy-роли не перенесены в v2

В `legacy/main.py` есть `/regleader`, `/regatt`, `/regadmin`, `/regmy` — привязка бесед и автоснятие при выходе. В v2 `/regrole` знает только `court | congress | sledca`.

#### D. Пулы без сферы

`Pool` не содержит `sphere_id`. Нельзя показать «этот пул — МЮ» или ограничить `/createpool` ведомством.

#### E. Бейджи без сферы

`/staff` показывает уровень и флаги (`［ЦА］`, `［🛡］`), но не `［ЗГС МЮ］` или `［Лидер ЦЛ］`.

#### F. «Добавить в конфу» ≠ назначить роль

**Групповой бот** (токен сообщества) сам в конфу людей не добавляет. Сейчас в коде нет ни `messages.addChatUser`, ни обёртки под invite.

«Добавление в конфу» на практике — один из путей:

1. Админ вручную добавляет в VK, **или**
2. Человек заходит по ссылке → бот **реагирует на join** (как `sled_ca`), **или**
3. **User-бот** (`VK_USER_TOKEN`) вызывает `messages.addChatUser`, если аккаунт токена — админ этой беседы (см. §2.4), **или**
4. Назначение должности (`/setspeaker`, `/addcourt`) **без** факта членства в беседе.

Спека разделяет **регистрацию беседы**, **назначение должности**, **invite (опционально)** и **реакцию на вход/выход**.

#### G. User-бот в проекте сегодня

В репозитории **нет отдельного процесса** «юзер-бота» — один опциональный токен пользователя `VK_USER_TOKEN` в `.env`.

| Где | Зачем |
|-----|--------|
| `services/messaging.py` | Fallback для `messages.getConversationMembers`: если групповой бот видит не всех участников, пробует user API |
| `modules/pools/handlers.py` | Тот же `user_api` для `/members` и пингов в `/msg` |
| `legacy/main.py` | `VkApi(token=VK_USER_TOKEN)` — отправка от имени пользователя (логи, часть UI) |

**Не используется:** приглашение в беседы, кик от user API, отдельные токены «на сферу» (РУК ЦА, РУК ГОС).

Без `VK_USER_TOKEN` в ROADMAP уже зафиксировано: `/members` и `/msg` могут отдавать **неполный** список участников.

---

### 2.4. User-бот и сферные конфы (целевое использование)

User-бот **не заменяет** модель сфер (`UserPosition`, `sphere_chats`), но может закрыть сценарий «назначили лидера ЦЛ → **добавить в нужную конфу**».

#### Что даёт VK user token

| Метод VK API | Условие | Применение для сфер |
|--------------|---------|---------------------|
| `messages.getConversationMembers` | Токен в беседе или групповой бот с правами | Проверка «уже в конфе?» перед invite; полный `/members` |
| `messages.addChatUser` | **Аккаунт токена — админ** целевой беседы | Авто-добавление после `/setposition` |
| `messages.removeChatUser` | То же | Снятие при `/setposition off` (опционально, осторожно с киком) |
| `messages.send` в беседу | Участник беседы | Напоминание «вас назначили, зайдите по ссылке» |

Групповой бот в мультибеседе обычно **не может** вызывать `addChatUser` за других — для invite нужен именно user token (или ручное действие человека).

#### Рекомендуемая архитектура (не в MVP, этап 2–3)

```text
UserTokenService (один VK_USER_TOKEN или пул)
├── get_members(peer_id)          — уже есть в MessagingService
├── can_invite(peer_id)           — токен в members + is_admin / creator
├── invite_to_chat(peer_id, vk_id) — messages.addChatUser
└── invite_for_position(position)  — peer из sphere_chats по сфере/unit/должности
```

Связка с командами:

```text
/setposition ca cl leader @user
  → UserPosition в БД
  → если sphere_chat.mode == AUTO_JOIN и user token может invite:
       addChatUser → on join → grant (или grant сразу + invite)
  → иначе: ЛС «вас назначили; беседа: <ссылка/название>»
```

Флаги на `sphere_chats` (расширение §4.3):

| Поле | Смысл |
|------|--------|
| `auto_invite` | bool, по умолчанию `false` |
| `invite_via` | `none` \| `user_token` \| `manual` |

#### Ограничения и риски user-бота

| Тема | Деталь |
|------|--------|
| **Один аккаунт** | Токен должен быть **админом во всех** сферных конфах, куда планируется auto-invite (РУК ЦА, лидеры ЦЛ, РУК ГОС…). Иначе — только ручное добавление |
| **Несколько юзер-ботов** | Теоретически: `VK_USER_TOKEN_CA`, `VK_USER_TOKEN_GOS` — усложняет деплой; имеет смысл только если один аккаунт не может быть админом всех бесед |
| **Безопасность** | User token = полный доступ к аккаунту; только на VPS, не в git, ротация при утечке |
| **ToS VK** | Автоматизация user-аккаунта на свой страх; групповой бот предпочтительнее для команд |
| **Права в беседе** | Invite не сработает, если токен не админ или у беседы закрыты приглашения |
| **rejoinkick** | После invite срабатывает тот же `invite_guard` — если человек раньше сам вышел, его могут сразу кикнуть |

#### MVP без user-бота (как сейчас)

Достаточно для пилота сфер:

- `/regspherechat` + join/leave (`AUTO_JOIN`)
- `/setposition` + текст «добавьте в беседу X вручную»
- опционально ЛС-напоминание через **групповой** бот

Auto-invite через `VK_USER_TOKEN` — **улучшение этапа 2–3**, не блокер для схемы БД и `sphere_chats`.

---

## 3. Целевая модель (to-be)

### 3.1. Термины

| Термин | Определение |
|--------|-------------|
| **Сфера** (`Sphere`) | Ведомство: ЦА, ГОС, МЮ, МО, МЗ, Суд, АК, Прочие… |
| **Подразделение** (`Unit`, опционально) | Фракция/центр внутри сферы: ЦЛ, FBI, LSPD, LSMC… |
| **Должность** (`Position`) | Организационная роль: `RUK`, `ZGS`, `LEADER`, `DEPUTY`, `OFFICER`… |
| **Сферная конфа** | VK-беседа, зарегистрированная как «беседа должности X в сфере Y (unit Z)» |
| **Назначение** (`UserPosition`) | Запись «пользователь P занимает должность D в сфере S» на сервере |

### 3.2. Иерархия (пример)

```text
Сервер
└── Сфера ЦА (CA)
    ├── Должность: РУК (head)          → беседа «Руководство ЦА»
    ├── Должность: ЗГС / ГС            → пулы staff ЦА
    ├── Должность: следящий            → /regrole sledca (уже есть)
    └── Подразделение ЦЛ (unit: CL)
        └── Должность: лидер           → беседа «Лидеры ЦЛ»

└── Сфера ГОС (GOS)
    ├── Должность: РУК ГОС             → беседа кабинета / руководства ГОС
    └── Конгресс                       → отдельный модуль (уже есть)

└── Сфера МЮ (MJ)
    ├── Должность: министр / РУК       → беседа МЮ (/regmy)
    └── Unit: FBI, LSPD, …
        └── Должность: лидер           → беседа лидеров фракции
```

### 3.3. Два режима сферной конфы

| Режим | Когда использовать | Пример | Поведение |
|-------|-------------------|--------|-----------|
| **AUTO_JOIN** | Должность = членство в беседе | след. ЦА, беседа лидеров ЦЛ | Вход → выдать права/флаг; выход → снять |
| **MANUAL_APPOINT** | Должность назначается сверху | РУК ЦА, спикер конгресса, судья | `/setposition` / `/setleader`; выход из беседы → снятие или предупреждение |

Режим задаётся при регистрации беседы, не выводится из сферы автоматически.

### 3.4. Матрица «кто может что» (черновик)

| Действие | Мин. уровень | Сфера / должность выдающего |
|----------|--------------|-----------------------------|
| `/regspherechat` | ЗГС (3) | ЦА: `requires_ca_scope`; ГОС: ур. 5+; внутри МЮ — ЗГС МЮ* |
| `/setposition` | Зависит от должности | РУК сферы → любая должность в своей сфере; ЗГС → только ниже себя |
| `/setca` | ЗГС + ЦА | Только флаг ЦА (как сейчас) |
| `/setlevel` | ЗГС | Опционально: только в своей сфере (фаза 5.7 ROADMAP) |

\* Делегирование по сферам — **фаза 2** после базовой модели; в MVP достаточно ур. 3+ ЦА или ур. 5+ ГОС для всех регистраций.

---

## 4. Предлагаемая схема данных

### 4.1. Таблица `spheres`

| Поле | Тип | Пример |
|------|-----|--------|
| `id` | PK | |
| `server_id` | FK | |
| `code` | str, unique per server | `CA`, `GOS`, `MJ`, `CL` |
| `name` | str | «Центральная администрация» |
| `parent_sphere_id` | FK nullable | ЦЛ → parent CA (если ЦЛ считается подразделением ЦА) |
| `sort_order` | int | для `/spheres` |

Сид при создании сервера: CA, GOS, MJ, MO, MZ, COURT, AK, OTHER.

### 4.2. Таблица `position_types` (справочник должностей)

| `code` | Название | Типичный min_level |
|--------|----------|-------------------|
| `RUK` | Руководитель | 4–6 |
| `ZGS` | Зам. главного следящего | 3 |
| `GS` | Главный следящий | 4 |
| `LEADER` | Лидер (фракции/центра) | 0–2 (форумная роль) |
| `DEPUTY` | Заместитель | — |
| `OFFICER` | Служебная роль (спикер, судья…) | — |

Связь с существующими флагами: `LEADER` → постепенная замена `is_leader`; `OFFICER` + unit `congress` → `is_congress_speaker`.

### 4.3. Таблица `sphere_chats` (замена расширенного `role_chats`)

| Поле | Тип | Комментарий |
|------|-----|-------------|
| `id` | PK | |
| `server_id` | FK | |
| `sphere_id` | FK | обязательно |
| `unit_code` | str nullable | `CL`, `FBI`, `LSPD`… |
| `position_code` | str | `RUK`, `LEADER`, `SLED`… |
| `peer_id` | bigint | VK peer |
| `mode` | enum | `AUTO_JOIN` / `MANUAL_APPOINT` |
| `alias` | str nullable | для `/msg` |
| `pool_id` | FK nullable | опциональная привязка к пулу |
| `registered_by`, `registered_at` | | аудит |

**Уникальность:** `(server_id, sphere_id, unit_code, position_code)` — одна каноническая беседа на должность в рамках сервера.

> Миграция: `role_chats` для `judge`, `congress`, `sled_ca` переносятся в `sphere_chats` с фиксированным маппингом (см. §6).

### 4.4. Таблица `user_positions`

| Поле | Тип |
|------|-----|
| `id` | PK |
| `user_id` | FK → users |
| `server_id` | FK |
| `sphere_id` | FK |
| `unit_code` | nullable |
| `position_code` | str |
| `granted_by` | bigint |
| `granted_at` | datetime |
| `source_peer_id` | bigint nullable | если выдано входом в беседу (как `ca_auto_peer_id`) |
| `expires_at` | nullable | и.о. на срок |

**Уникальность (мягкая):** один активный `RUK` на `(server, sphere)`; несколько `LEADER` на разных `unit_code`.

### 4.5. Расширение `UserServerAccess` (опционально)

| Поле | Зачем |
|------|-------|
| `primary_sphere_id` | Основная сфера для бейджа «ЗГС МЮ» |
| `has_ca_access` | **Оставить** — поперечный флаг ЦА, не смешивать с `UserPosition` |

ЦА остаётся **поперечным слоем** (как сейчас): доступ к конгрессу/суду для ур. 1–4, не заменяется сферой.

### 4.6. Расширение `Pool`

```text
Pool.sphere_id  — nullable FK
Pool.unit_code  — nullable (пул «лидеры FBI»)
```

---

## 5. Команды (целевой UX)

### 5.1. Регистрация бесед

Единая команда вместо разрозненных `/regleader`, `/regmy`, `/regrole …`:

```text
/regspherechat <сфера> [unit] <должность> [alias] [--mode auto|manual]

Примеры:
/regspherechat ca ruk              → беседа РУК ЦА (manual)
/regspherechat ca cl leader        → беседа лидеров ЦЛ (auto)
/regspherechat gos ruk кабинет     → беседа РУК ГОС + алиас для /msg
/regspherechat mj leader           → общая беседа лидеров МЮ (legacy /regleader)
/regspherechat mj fbi leader       → беседа лидеров FBI
```

**Алиасы для обратной совместимости:**

| Старая команда | Новый вызов |
|----------------|-------------|
| `/regrole sledca` | `/regspherechat ca sled` или оставить алиас |
| `/regrole court` | `/regspherechat court judge` |
| `/regrole congress` | без изменений (конгресс — отдельный модуль) |
| `/regleader` | `/regspherechat mj leader` |
| `/regmy` | `/regspherechat mj ruk` или `mj ministry` |

### 5.2. Назначение должности

```text
/setposition <сфера> [unit] <должность> [@user|ник] [off]

Примеры:
/setposition ca ruk @ivan          → назначить РУК ЦА
/setposition ca cl leader Никита   → лидер ЦЛ
/setposition gos ruk               → ответом на сообщение
/setposition mj fbi leader off     → снять
```

Правила:

- Нельзя назначить **себе** `RUK` / `LEADER` без ур. 5+ (аналогично `/raccess`).
- Снятие: `off` или `/raccess` расширить списком сферных должностей.
- При `MANUAL_APPOINT` бот **не добавляет** в беседу — только пишет в ответе peer_id / ссылку-подсказку.

### 5.3. Просмотр

```text
/spheres              — список сфер, бесед, пулов
/sphere ca            — карточка ЦА: беседы, должности, кто занимает
/myposts              — мои должности на сервере
/staff --sphere mj    — staff с фильтром по сфере (позже)
```

### 5.4. Поведение join / leave (общий обработчик)

Заменить разрозненные `handle_sled_ca_*`, `handle_role_chat_leave` на:

```text
on_chat_join(peer_id, user_id):
  chat = resolve_sphere_chat(peer_id)
  if chat.mode == AUTO_JOIN:
    grant_from_chat(user_id, chat)   # UserPosition + опционально level/CA

on_chat_leave(peer_id, user_id):
  chat = resolve_sphere_chat(peer_id)
  if chat.mode == AUTO_JOIN:
    revoke_if_source_peer(user_id, chat)
  elif chat.mode == MANUAL_APPOINT:
    revoke_position_if_matched(user_id, chat)  # как судья/лидер в legacy
```

Логика `ca_auto_peer_id` обобщается в `UserPosition.source_peer_id`.

---

## 6. Маппинг текущего кода → целевая модель

| Сейчас | Куда переезжает |
|--------|-----------------|
| `ForumRoleKey.SLED_CA` + `grant_sled_ca_from_chat` | `sphere=CA`, `position=SLED`, mode=AUTO_JOIN + `has_ca_access` |
| `ForumRoleKey.JUDGE` | `sphere=COURT`, `position=JUDGE`, mode=MANUAL (или AUTO) |
| `ForumRoleKey.LEADER` | `sphere=MJ` (или по unit), `position=LEADER` |
| `ForumRoleKey.MINISTRY` | `sphere=MJ`, `position=RUK` или `MINISTRY` |
| `ForumRoleKey.ADMIN` | `sphere=CA`, `position=ADMIN` |
| `CongressRepository` | `sphere=GOS`, `position=SPEAKER/VICE` — **можно не трогать** в первой итерации |
| `has_ca_access` | **Не удалять** — поперечный флаг; sled_ca по-прежнему его выставляет |

### Примеры из запроса

| Роль | sphere | unit | position | mode | Кто регистрирует беседу | Кто назначает |
|------|--------|------|----------|------|-------------------------|---------------|
| РУК ЦА | CA | — | RUK | manual | ЗГС+ ЦА | ГС ЦА / ГА |
| РУК ГОС | GOS | — | RUK | manual | ур. 5+ | ГС ГОС / куратор+ |
| Лидер ЦЛ | CA | CL | LEADER | auto | ЗГС+ ЦА | вход в беседу или `/setposition` |
| Лидер FBI | MJ | FBI | LEADER | auto | ЗГС+ ЦА или ЗГС МЮ* | РУК МЮ / вход в беседу |

---

## 7. План внедрения (только этапы, без кода)

### Этап 0 — Решения сообщества (блокер)

Зафиксировать ответы из [ROADMAP.md § «Открытые вопросы»](../ROADMAP.md):

1. **ЦА vs ГОС в уровнях 3–6** — сфера в бейдже отдельно от числа уровня?
2. **Несколько сфер у одного человека** — приоритет при конфликте `/setlevel` и автоснятия.
3. **ЦЛ** — подсфера ЦА (`parent_sphere_id=CA`) или отдельная сфера `CL`?
4. **Мульти-сервер** — один справочник сфер на все Arizona-серверы или per-server.

Без §0 нельзя корректно сидировать `spheres` и уникальные ключи.

### Этап 1 — Схема + миграция `sphere_chats` (MVP)

- [ ] Модели `Sphere`, `SphereChat`, сид CA/GOS/MJ/COURT/OTHER.
- [ ] Миграция существующих `role_chats` (judge, sled_ca, congress) в `sphere_chats`.
- [ ] `resolve_sphere_chat(peer_id)` вместо `find_role_by_peer`.
- [ ] `/regspherechat` для **двух пилотов**: `ca cl leader`, `ca ruk`.
- [ ] Join/leave для пилотов по образцу `services/ca_access.py`.

**Критерий:** лидер ЦЛ заходит в зарегистрированную беседу → появляется `UserPosition`; выходит → снимается.

### Этап 2 — Назначение и отображение

- [ ] `/setposition`, расширение `/raccess`.
- [ ] `/sphere`, `/spheres`, бейджи в `/staff`: `［Лидер ЦЛ］`, `［РУК ГОС］`.
- [ ] `UserServerAccess.primary_sphere_id` + бейдж `［ЗГС МЮ］`.

### Этап 3 — Legacy-паритет

- [ ] `/regleader`, `/regmy`, `/regatt`, `/regadmin` → алиасы `/regspherechat`.
- [ ] Перенос автоснятия лидера/адвоката из legacy в v2.
- [ ] Постановления МЮ (пинг лидеров в беседе) — привязка к `sphere_chats` MJ.

### Этап 4 — Пулы, матрица, делегирование

- [ ] `Pool.sphere_id`, `/createpool --sphere`.
- [ ] Модуль `AccessMatrix` (ROADMAP 5.6).
- [ ] Ограничение `/setlevel` по сфере (ROADMAP 5.7).

---

## 8. Изменения по файлам (ориентир для разработки)

| Область | Файлы сейчас | Что менять |
|---------|--------------|------------|
| Модели | `database/models/role_chat.py`, `user.py`, `pool.py` | `sphere.py`, `sphere_chat.py`, `user_position.py`; deprecate PK `role` |
| Репозитории | `forum_role_repo.py`, `user_repo.py` | `sphere_repo.py`, `position_repo.py`; обобщить grant/revoke |
| Join/leave | `services/ca_access.py`, `role_chat_leave.py` | `services/sphere_chat_access.py` |
| Команды | `modules/ca/handlers.py` | `modules/sphere/handlers.py` или расширить `ca` |
| Middleware | `ca_access.py`, `forum_access.py` | `requires_sphere_scope(sphere, min_level)` |
| Staff | `services/staff_display.py` | бейджи из `UserPosition` + `primary_sphere` |
| Help | `services/help_menu.py` | новые команды после реализации |

---

## 9. Риски и антипаттерны

| Риск | Митигация |
|------|-----------|
| Дублирование с `has_ca_access` | ЦА-флаг оставить для поперечных команд; сфера — для организационной структуры |
| Сломать единственный `role_chats.pk` при миграции | Dual-read: сначала читать `sphere_chats`, fallback на `role_chats` |
| Человек в двух беседах AUTO_JOIN одной должности | `source_peer_id` только одна; второй вход не перезаписывает без `/setposition` |
| Invite в конфу | Групповой бот — нет; user token — да, если админ беседы; fallback: ручное добавление + peer_id |
| User token утёк / не админ | `auto_invite=false`, только напоминание в ЛС |
| Раздувание справочника должностей | Начать с `RUK`, `LEADER`, `SLED`; остальное — по мере переноса legacy |

**Не делать:** хранить «лидер ЦЛ» только в `is_leader=true` без `UserPosition` — это воспроизводит текущий тупик.

---

## 10. Открытые вопросы (дополнение к ROADMAP)

1. **ЦЛ** — код сферы `CL` с parent=CA или unit `CL` внутри сферы CA? (рекомендация: **unit внутри CA**, чтобы не плодить сферы.)
2. **РУК ЦА vs ГА** — одна беседа или разные (`ca ruk` vs `ca ga`)?
3. **Лидер ЦЛ** — достаточно AUTO_JOIN или обязательное `/setposition` до входа?
4. **Связь с форумом** — лидер ЦЛ на форуме = автоматом `UserPosition` или только VK-беседа?
5. **Invite при назначении** — только напоминание в ЛС, или `messages.addChatUser` через `VK_USER_TOKEN`? (нужен один сервисный аккаунт-админ во всех сферных конфах)
6. **Сколько user-токенов** — один на весь сервер или отдельно на ЦА / ГОС / МЮ?

---

## 11. Краткий чеклист «что надо сделать»

1. **Принять решения** по §7 этап 0 (ЦЛ, ЦА/ГОС, мульти-сфера).
2. **Спроектировать БД:** `spheres`, `sphere_chats`, `user_positions` (§4).
3. **Снять ограничение** «одна беседа на роль» (`RoleChat.role` PK).
4. **Обобщить join/leave** с `sled_ca` на любую `sphere_chat` с `AUTO_JOIN`.
5. **Ввести `/regspherechat` и `/setposition`** с пилотом: РУК ЦА, РУК ГОС, лидер ЦЛ.
6. **Перенести legacy** `/regleader`, `/regmy` и автоснятие лидера.
7. **Обновить `/staff`, `/help`, ROADMAP** после появления команд в коде.
8. **Привязать пулы к сферам** и вынести `AccessMatrix` в отдельный модуль.
9. **(Опционально)** `UserTokenService` + `auto_invite` на `sphere_chats` для `/setposition` → `addChatUser`.

---

## 12. Связь с ROADMAP

Документ детализирует задачи **фазы 5** (п. 5.1–5.4, 5.9) вокруг **конференций по сферам**. Реализованный слой ЦА (июнь 2026) — **не отменяется**, а становится частным случаем:

```text
/regrole sledca  ≡  /regspherechat ca sled  (AUTO_JOIN → has_ca_access + ур.1)
```

Дальнейшая работа в коде — после закрытия открытых вопросов §10 и утверждения пилота (лидер ЦЛ + РУК ЦА + РУК ГОС).
