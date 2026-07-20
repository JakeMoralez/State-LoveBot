# State Love

VK administration bot + CA staff web panel — **monorepo** (see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)).

## Chapters (apps)

| App | Role | Today |
|-----|------|--------|
| Bot | VK Long Poll (vkbottle) | Root `main.py` — still the production entry |
| Web API | FastAPI | Sibling `State-LoveAdmin/backend` until moved to `apps/web-api` |
| Web UI | React / Vite | Sibling `State-LoveAdmin/frontend` until moved to `apps/web-ui` |

Shared logic lives under `packages/` (`domain` → `application` ← `infra`).

## Quick start (bot, as before)

```bash
python -m venv venv
# Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env   # fill secrets
python main.py
```

## Target (after later waves)

- One Postgres DB `state_love`
- One `.env` `DATABASE_URL`
- Bot and API call the same use-cases; bot does not open panel tables with raw SQL

## Deploy

See `deploy/README.md` and `deploy/postgres/README.md`.
