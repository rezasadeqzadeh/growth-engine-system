# Growth Engine

A raw video sent with a tag to a Bale or Telegram bot comes back as a
finished post for every channel: cut, Persian subtitles burned in, cover,
logo, and a caption for each channel. After one tap it is published
everywhere, and the result is measured all the way to registration and
payment. Design: `growth-engine-system-v2.pdf` (the eight modules below).

Separate from app-builder: its own repo, database and sign-in. The only AI
provider is the OpenCode server (same protocol as app-builder).

## Modules (design section → code)

| Design module | Code |
|---|---|
| 1 Page audit (lead magnet) | `services/audit.py`, `api/audits.py`, panel `/audit` |
| 2 Brand kit | `services/brand_kit.py`, panel `/w/:id/brand` |
| 3 Tag-driven video pipeline | `bots/gateway.py` → `services/pipeline.py` → `media/*` → `services/approval.py` |
| 4 Content calendar + content requests | `services/calendar.py`, `services/iran_calendar.py` |
| 5 Multi-channel publishing | `channels/*` (Bale, Telegram, Aparat, Eitaa, Rubika, Instagram, site), `services/publishing.py` |
| 6 Feedback inbox | `services/feedback.py`, `services/metrics.py` (Insights OCR) |
| 7 Competitor analysis | `services/competitors.py` |
| 8 Measurement + weekly report | `services/links.py`, `services/offers.py`, `services/metrics.py`, `services/reports.py`, `public/pages.py` |
| P3 agency, self-serve, white label | `services/agency.py`, `services/billing.py`, panel `/agency` |

## Architecture

```
Bale/Telegram bots ──webhook──► API (FastAPI) ◄── panel (Next.js, fa/RTL)
                                  │   public pages: /b/<code> links, /o offers + Zarinpal,
                                  │   /s site channel, /h Instagram handoff, /up direct upload
                                  ▼
                           PostgreSQL ◄── jobs table (FOR UPDATE SKIP LOCKED)
                                  ▲            │
          scheduler (periodic) ───┘     worker (default) / media worker (FFmpeg, Whisper, OpenCV)
                                                  │
                                       OpenCode server (all LLM calls, ai/opencode.py)
```

- The job queue is a table: a job and the rows it creates commit together.
- Files are self-hosted (`STORAGE_DIR`), handed out only as signed, expiring URLs.
- Credentials never leave the backend: the API reports only which secrets are
  set; every adapter error passes through `redact.py`.

## Facts that shaped the code

- **Bale** bots get no `channel_post` updates and download at most 20 MB: admins send raw
  video in a private group with the bot or to the bot itself; bigger files get a direct upload link.
- **Telegram** bots download at most 20 MB unless `TELEGRAM_API_BASE` points at a local Bot API server.
- **Aparat** (legacy `etc/api`): login → upload form → multipart upload; no subtitle upload, so the
  SRT is sent to the admin in the bot.
- **Instagram**: the official API (Instagram Login) publishes, reads comments and insights. Receiving
  DMs did not work in app-builder, so calls to action send people to the bot. Without a connection
  the one-click handoff page is used.
- **libass** needs `Encoding=-1` for right-to-left base direction (with 1, Persian words came out reversed).
- Lunar occasions use the tabular Hijri calendar and can be a day off.
- **Not verified against the live services**: the Eitaa (eitaayar.ir) and Rubika bot APIs and the Aparat
  upload are built from their published client libraries; test each with a real account before relying on it.

## Run locally

```bash
python3 -m venv .venv && .venv/bin/pip install -e "backend[test]"
cd backend && ../.venv/bin/alembic upgrade head
../.venv/bin/uvicorn growth_engine.main:app --reload          # API on :8000
../.venv/bin/python -m growth_engine.jobs.runner default       # worker
../.venv/bin/python -m growth_engine.jobs.runner media         # media worker (needs ffmpeg + .[media])
../.venv/bin/python -m growth_engine.jobs.scheduler            # periodic jobs
cd ../frontend && npm install && npm run dev                   # panel on :3000
```

## Deploy (Coolify, as app-builder)

Two Coolify applications from this repo, branch `main`, build pack Dockerfile, base directory `/`:

| App | Dockerfile | Port | Notes |
|---|---|---|---|
| backend | `backend/Dockerfile` | 8000 | env from `.env.example`; persistent volume at `/data`; `ROLE=all` (default) runs API + workers + scheduler; set `ROLE=api|worker|media|scheduler` to split across apps |
| frontend | `frontend/Dockerfile` | 3000 | build arg `NEXT_PUBLIC_API_BASE` = the backend's public URL |

The backend runs `alembic upgrade head` on start. The database `growth_engine` must exist on the
Postgres server in `DATABASE_URL`. Locally: `docker compose up --build`.

## Tests

```bash
cd backend && ../.venv/bin/python -m pytest -q                      # SQLite, ~1.5 min
GE_TEST_DATABASE_URL=postgresql+psycopg://... ../.venv/bin/python -m pytest -q   # on Postgres
PATH=<ffmpeg dir>:$PATH GE_TEST_FONTS_DIR=<Vazirmatn dir> ../.venv/bin/python -m pytest tests/test_render_ffmpeg.py
cd ../frontend && npm run typecheck && npm run build
```
