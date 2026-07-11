# arya-hack

A post-op voice agent for **recently-discharged elderly patients** — many of whom go
home alone. arya phones them to check in ("How's the pain? Are you eating? Any
dizziness or bleeding?"), listens, and then **notifies their loved ones** with a
plain-language recap — escalating to family and the care team when something sounds
concerning. Built on **Twilio** (telephony) + **ElevenLabs** (Conversational AI voice).

> Early scaffold. The schema and endpoints are intentionally minimal and easy to reshape.

## Layout

```
arya-hack/
├── web/    # Next.js dashboard — doctor / healthcare professional view
└── api/    # FastAPI backend — Twilio <-> ElevenLabs bridge + data endpoints
```

## Quick start

**Backend** (`api/`) — see [`api/README.md`](api/README.md):

```bash
cd api
uv sync
cp ../.env.example ../.env          # fill in DB + Twilio + ElevenLabs
uv run python scripts/init_db.py
uv run uvicorn app.main:app --reload --port 8080
```

**Frontend** (`web/`):

```bash
cd web
bun install
bun run dev                          # http://localhost:3000
```

## How the call flow works

1. A check-in is triggered: `POST /call/outbound/{patient_id}` dials the patient via
   Twilio. (Patients can also call in — same bridge.)
2. When they answer, Twilio hits `POST /call/incoming` → TwiML opens a media stream to
   `WS /call/stream`, which the backend bridges to an ElevenLabs Conversational AI
   agent, transcoding audio both ways (mu-law 8kHz ↔ PCM16 16kHz).
3. Transcript turns are persisted live. On hangup, the post-call pipeline runs:
   - **analyze** (`analysis.py`) → summary + triage `{level: ok|monitor|urgent, flags}`
     (Claude when `ANTHROPIC_API_KEY` is set, else a keyword heuristic).
   - **notify** (`notify.py`) → texts each caregiver whose `notify_when` preference
     matches (`always` / `urgent` / `never`).
4. The care team watches it all on the dashboard (`/api/patients/*`, `/api/calls/*`,
   `/api/.../caregivers`). See [`api/README.md`](api/README.md) for the full endpoint map.

## Data model

- **Patient** — the discharged person (name, phone, procedure, surgery date, clinician).
- **Caregiver** — a loved one / emergency contact, with a per-contact notify preference.
- **Call** + **TranscriptTurn** — each check-in, its transcript, summary, and triage.

## Reference

Backend architecture mirrors the `attune` project's voice pipeline.
