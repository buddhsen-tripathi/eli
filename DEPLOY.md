# Deploy

Two services: **backend** (`api/`) on Render, **frontend** (`web/`) on Vercel.
They share the Neon Postgres DB. Deploy the backend first — the frontend and
Twilio both need its URL.

## 0. Database (already done)

Tables are created with `create_all` (no Alembic yet):

```bash
cd api && uv run --env-file ../.env python scripts/init_db.py
```

Idempotent — creates missing tables only. It does **not** alter existing columns, so
for future schema *changes* introduce Alembic (`alembic init`, autogenerate, `upgrade`)
rather than relying on this script.

## 1. Backend → Render

Uses `render.yaml` (Blueprint). Root dir `api`, Python 3.13 (`api/.python-version`).

1. Render dashboard → **New → Blueprint** → pick this repo. It reads `render.yaml`.
2. Set the secret env vars (all `sync:false`): `DATABASE_URL`, `TWILIO_ACCOUNT_SID`,
   `TWILIO_AUTH_TOKEN`, `TWILIO_PHONE_NUMBER`, `ELEVENLABS_API_KEY`,
   `ELEVENLABS_AGENT_ID`, `ANTHROPIC_API_KEY`.
   - Leave `PUBLIC_BASE_URL` and `CORS_ORIGINS` blank for now (step 3/5).
3. Deploy. Note the public URL, e.g. `https://arya-api.onrender.com`.
   Verify: `GET /health` → `{"status":"ok"}`.
4. Set `PUBLIC_BASE_URL` = that URL (no trailing slash) → triggers a redeploy.

- Build: `pip install -r requirements.txt` · Start: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
  - `requirements.txt` is generated from the uv lockfile. Regenerate after changing deps:
    `cd api && uv export --no-dev --no-hashes --no-emit-project -o requirements.txt`
- WebSockets (the Twilio ↔ ElevenLabs bridge at `/call/stream`) work on Render web
  services. **Use the `starter` plan, not free** — free instances sleep after ~15 min
  idle and the first Twilio webhook after a sleep will time out mid-call.

## 2. Frontend → Vercel

1. Vercel → **Add New → Project** → import this repo.
2. Set **Root Directory = `web`** (Next.js auto-detected from there).
3. Env var `NEXT_PUBLIC_API_URL` = the Render URL from step 1.3.
4. Deploy. Note the URL, e.g. `https://arya-hack.vercel.app`.

## 3. Wire the two together

- Back on **Render**, set `CORS_ORIGINS` = your Vercel URL (comma-separated if more
  than one, e.g. `https://arya-hack.vercel.app,http://localhost:3000`). Redeploy.

## 4. Point Twilio at the backend

In the Twilio Console → your number → Voice config:
- **A call comes in** → Webhook → `POST {PUBLIC_BASE_URL}/call/incoming`

Outbound check-ins already build their callback URLs from `PUBLIC_BASE_URL`, so no
extra Twilio config is needed for those.

## Env var matrix

| Variable              | Render (api) | Vercel (web) | Notes                                    |
|-----------------------|:------------:|:------------:|------------------------------------------|
| DATABASE_URL          | ✅           |              | Neon pooled connection string            |
| TWILIO_ACCOUNT_SID    | ✅           |              |                                          |
| TWILIO_AUTH_TOKEN     | ✅           |              |                                          |
| TWILIO_PHONE_NUMBER   | ✅           |              |                                          |
| ELEVENLABS_API_KEY    | ✅           |              |                                          |
| ELEVENLABS_AGENT_ID   | ✅           |              |                                          |
| ANTHROPIC_API_KEY     | ✅           |              | optional — heuristic fallback if unset   |
| PUBLIC_BASE_URL       | ✅           |              | = the Render URL (set after 1st deploy)  |
| CORS_ORIGINS          | ✅           |              | = the Vercel URL                         |
| NEXT_PUBLIC_API_URL   |              | ✅           | = the Render URL                         |

## Smoke test after deploy

```bash
curl https://arya-api.onrender.com/health           # {"status":"ok"}
# create a patient
curl -X POST https://arya-api.onrender.com/api/patients \
  -H 'content-type: application/json' \
  -d '{"name":"Test Patient","phone":"+15551234567","procedure":"hip replacement"}'
# then trigger a check-in call:
# curl -X POST https://arya-api.onrender.com/call/outbound/<patient_id>
```
