# Growth Engine — working rules

- Never show a credential (bot token, access token, Aparat login, OpenCode password, .env value)
  to the user, in the panel, a bot message, a log line meant for people, or a job error.
  Adapter errors go through `growth_engine/redact.py`; the channels API returns only `secrets_set`.
- English in source code. Persian lives in `backend/growth_engine/i18n/fa.json`,
  `backend/growth_engine/data/*.json` and `frontend/lib/fa.ts` (`tests/test_planning_and_insight.py`
  checks every backend key exists; TypeScript checks the panel's).
- Every LLM call goes through `ai/router.py` → `ai/opencode.py` with a task name. No other provider.
- A job that writes rows commits before calling the AI or running long media work: the router
  records usage in its own session (SQLite deadlocked; Postgres held long transactions).
- Datetimes are timezone-aware; the database stores UTC (`db.UTCDateTime` refuses naive values).
- Nothing is published without an approval, except a low-risk tag whose owner consented.
- Fix only what was asked; prove a fix with a test that failed before it.
- Run targeted tests while iterating; the whole suite before a commit.
- Keep `docs/sequence-diagrams/` true when a flow changes.
