# arya-api

FastAPI backend for the post-op voice agent. Bridges Twilio phone calls to an
ElevenLabs Conversational AI agent and exposes call/patient data to the dashboard.

## Setup

```bash
cd api
uv sync                       # or: python -m venv .venv && pip install -e ".[dev]"
cp ../.env.example ../.env     # fill in DB + Twilio + ElevenLabs creds
uv run python scripts/init_db.py   # create tables on a fresh DB
uv run uvicorn app.main:app --reload --port 8080
```

- Docs: http://localhost:8080/docs
- Health: http://localhost:8080/health

## Structure

```
app/
  main.py        # FastAPI app + router registration + CORS
  database.py    # async SQLAlchemy engine (Postgres via asyncpg)
  db_models.py   # Patient, Caregiver, Call, TranscriptTurn
  voice.py       # Twilio <-> ElevenLabs WebSocket bridge  (POST /call/incoming, WS /call/stream)
  outbound.py    # place an outbound check-in call         (POST /call/outbound/{patient_id})
  analysis.py    # transcript -> summary + triage          (Claude, or keyword fallback)
  notify.py      # text caregivers based on triage         (Twilio SMS)
  calls.py       # call + transcript data endpoints        (/api/calls/*)
  patients.py    # patient CRUD                             (/api/patients/*)
  caregivers.py  # caregiver CRUD                           (/api/patients/{id}/caregivers)
scripts/
  init_db.py     # create_all() for a fresh database
```

## Post-call pipeline

When a call ends, `voice.py` fires (off the request path):
`analysis.analyze_call()` → `notify.notify_caregivers()`. Trigger it manually against
an existing call with `POST /api/calls/{call_id}/rerun` (handy for testing without a
live phone call).

## Exposing to Twilio (local dev)

Twilio needs a public HTTPS URL. Use ngrok (or similar) and set `PUBLIC_BASE_URL`:

```bash
ngrok http 8080          # copy the https URL into .env as PUBLIC_BASE_URL
```

Point your Twilio number's Voice webhook at `POST {PUBLIC_BASE_URL}/call/incoming`.

## Notes

- Voice endpoints live under `/call/*` (Twilio-facing); data endpoints under `/api/*`.
- Call credentials are read lazily, so the API boots without Twilio/ElevenLabs keys.
- `audioop-lts` is required on Python 3.13+ (stdlib `audioop` was removed) — the
  voice bridge transcodes Twilio mu-law 8kHz <-> ElevenLabs PCM16 16kHz with it.
```
