# Architecture — State Love (monorepo)

## Decisions

| Topic | Choice |
|-------|--------|
| Layout | One git repo (book with chapters) |
| Database | One Postgres database (`state_love`) |
| Bot ↔ panel data | Shared use-cases + repositories (2a), **no** raw `panel_db` SQL in bot handlers |
| Frontend | Lives in `apps/web-ui` (moved from State-LoveAdmin) |

## Layers

```text
apps/bot, apps/web-api, apps/web-ui   → adapters (thin)
packages/application                 → use-cases
packages/domain                      → entities / rules / errors
packages/infra                       → Postgres, forum, VK (implements ports)
```

Dependencies point inward only: adapters → application → domain.  
`infra` implements ports defined for application; domain never imports infra.

## Migration waves

| Wave | Status | Goal |
|------|--------|------|
| 0 | in progress | Skeleton `packages/` + `apps/` stubs; root bot still runs |
| 1 | pending | One `DATABASE_URL`; merge `state_love_bot` + `state_love_panel` |
| 2 | pending | Nickname / profile / access use-cases |
| 3 | pending | Discord + staff_notes via use-cases; remove bot `panel_db` raw path |
| 4 | pending | Spheres / CA |
| 5 | pending | Court claims / judges |
| 6 | pending | Checklist / tasks / question banks in web-api |
| 7 | pending | Move frontend into `apps/web-ui` |
| 8 | pending | Drop legacy dual-DB env; delete dead code |

## Runtime (unchanged in wave 0)

- Bot: `python main.py` (systemd `state-lovebot`)
- Admin API: State-LoveAdmin uvicorn (until wave 7+)
- Do not change visible bot/site behavior without explicit approval.

## Import path

With cwd = repo root (and venv):

```python
from packages.domain import AccessLevel, DomainError
```
