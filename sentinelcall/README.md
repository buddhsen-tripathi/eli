# SentinelCall

**An accessibility-first post-op voice agent that leaves no elderly patient behind.**
Healthcare Hack NYC (Twilio × Arya Health).

A cascaded, guardrailed Twilio voice agent that phones elderly **post-operative**
patients, runs a structured recovery check-in, and is engineered so that
**slurred / quiet / accented speech degrades gracefully instead of failing
silently**. It **never diagnoses** — it collects, reads back the patient's own
discharge instructions, and **routes** anything clinical to a human.

> **General, not knee-only.** Knee replacement is the first *protocol pack*, not
> the ceiling. The patient record, safety spine, and pipeline are surgery-agnostic;
> Layer-2 reference retrieval selects `protocol_<surgery>.md` by the patient's
> surgery and falls back to `protocol_generic.md`. The seed data includes a hip
> patient (P002) to prove it.

---

## The hero: live speech recovery (GER)

Even strong ASR hits ~52% word-error-rate on dysarthric speech — a naive
"Deepgram-and-go" pipeline mis-hears **one in four to one in two** utterances
from exactly the patients who get readmitted. SentinelCall's **Generative Error
Correction (GER)** stage takes the ASR **N-best hypotheses** and lets Claude
pick/repair the most clinically-plausible transcription using narrow post-op
domain context:

```
raw ASR N-best:  "my insshun is red an wet"  /  "my in shun is read and wet"
GER recovered:   "my incision is red and weeping"   (confidence 0.95)
```

If confidence stays **low** on a **safety-critical** field, GER does **not
guess** — it emits a read-back confirmation instead ("I heard your incision is
red — did I get that right?"). Uncertainty never clears a red flag.

This is real: even clean Cartesia audio, Deepgram transcribes *"incision"* as
*"decision"* — GER recovers it every time.

---

## Quick start

```bash
# 1. Python 3.10+ (this build uses 3.11)
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt      # or:  pip install -e .

# 2. Configure keys
cp .env.example .env                  # fill in ANTHROPIC/DEEPGRAM/CARTESIA (+ Twilio for real calls)
sentinel check                        # shows which keys/config are present

# 3. See the whole thing work with NO phone required:
sentinel demo                         # the scripted 6-beat demo (winning path)
sentinel sim P001                     # interactive: type patient turns
sentinel sim P001 --audio             # your line is spoken (Cartesia) + re-transcribed (Deepgram N-best) -> real GER
sentinel sim P003 --inbound           # inbound Q&A mode
```

### Showing GER in the interactive simulator (no mic)

Prefix a line with `ASR:` and separate alternative hypotheses with `||` to feed
raw N-best straight into the pipeline:

```
PATIENT> ASR: my insshun is red an wet || my in shun is read and wet
```

---

## Placing a real phone call (the live demo finale)

Twilio is mandatory and this places a **real, dialable call**.

```bash
# Terminal 1: run the webhook server
sentinel serve                        # FastAPI on :8080

# Terminal 2: expose it so Twilio can reach your webhooks
ngrok http 8080
# copy the https URL into .env as PUBLIC_BASE_URL (no trailing slash), restart `serve`

# Point your Twilio number's Voice webhook at:   POST  {PUBLIC_BASE_URL}/voice/inbound
# Then place the OUTBOUND check-in call:
sentinel call P001
```

- **Outbound** (`sentinel call <id>`): SentinelCall dials the patient, greets by
  name / surgery / post-op day, and runs the S0–S7 check-in.
- **Inbound**: the patient dials your Twilio number; recognized by phone → same
  agent, open-ended grounded Q&A, **emergency screen first**.
- Patient turns are **recorded** (not `<Gather>`) so we run our own **Deepgram
  N-best → GER** on the phone — the hero is live on the call.
- Escalations fire **Twilio SMS** to the nurse (clinical) or volunteer
  (presence-only). If Twilio SMS isn't configured, the exact message is rendered
  to the trace so the demo still shows it.

---

## The demo path (what `sentinel demo` shows)

1. **Outbound call** — agent greets by name, knows surgery + post-op day.
2. **Slurred/quiet voice → garbled ASR → GER recovers it LIVE** (raw + repaired
   shown on screen). *(the hero)*
3. **Spreading redness + fever** → agent calmly instructs, **no diagnosis**,
   routes to a human. *(safety)*
4. **Nurse gets a structured escalation SMS** — what changed, which signals.
5. **Inbound callback** — "is it normal that it itches?" → grounded reassurance
   from the discharge record. *(two-way)*
6. **Green signal (missed calls)** → SMS routes to a **volunteer**, never a
   nurse, and **never carries clinical content**. *(ecosystem routing)*

---

## Architecture (cascaded — every stage is inspectable)

```
Patient audio ─▶ STT (Deepgram N-best) ─▶ EMERGENCY SCREEN (rule-based, FIRST, pre-LLM)
   ─▶ GER (N-best → repaired + confidence)  ─▶ EMERGENCY RE-SCREEN
   ─▶ SUPERVISOR (constrained S0–S7 state machine; never diagnoses)
        ├─ red-flag engine (rule/threshold-based) ─▶ ESCALATE ─▶ Twilio SMS (nurse | volunteer)
        └─ SAFETY GATE on every candidate line (blocks diagnosis/dose; grounds claims)
   ─▶ TTS (Cartesia slow/high-prosody preset)  ─▶ spoken line
```

### The safety spine (never bypassed)

- **Emergency screen runs FIRST**, rule-based, pre-LLM, on every turn — it can't
  be reasoned away. Chest pain / can't breathe / uncontrolled bleeding /
  fall-can't-get-up → "Hang up and call 911 now" + alert.
- **Safety gate on every spoken line** — blocks diagnosis / treatment / dose
  language; any dose number must trace to the patient's Layer-1 record; appends
  the safety-net line.
- **Negative confirmation** — low-confidence on a safety-critical field
  escalates or reads back; it never reassures.
- **Never says "you're fine."** Every reply ends with *"If anything gets worse,
  call your nurse line or 911."*

### The three data layers (deliberately not one RAG store)

| Layer | What | Storage | RAG'd? |
|------|------|---------|--------|
| **1 · Prescribed** | meds, verbatim doses, wound-care, follow-up, thresholds | structured JSON (`patients.json`) | **NO** — quoted verbatim |
| **2 · Reference** | "what's normal at day 5," red-flags | markdown per surgery | **YES** — the only RAG layer |
| **3 · Discussed** | what the patient reported | structured fields per call (`call_records.json`) | **NO** — trended, not RAG'd |

### The ecosystem barrier (enforced in code)

Volunteers handle **presence**; they **never** handle medicine. Clinical flags
route to the **nurse** channel only. The volunteer SMS body is generated from a
separate, sanitized template that carries **no symptoms, meds, wound detail, or
diagnosis** — the system literally cannot send clinical content down the
volunteer channel.

---

## CLI reference

```
sentinel check                 report which API keys / config are present
sentinel patients              list the seeded demo patients
sentinel demo [--no-pause]     scripted end-to-end demo (no phone)
sentinel sim <id> [--audio] [--inbound]   local simulator of the full pipeline
sentinel serve [--port]        run the inbound/outbound webhook server
sentinel call <id>             place a real outbound Twilio call
```

## What you need in `.env`

Minimum for the demo/simulator (no phone): `ANTHROPIC_API_KEY`,
`DEEPGRAM_API_KEY`, `CARTESIA_API_KEY`, `CARTESIA_VOICE`.
For real calls also: `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`,
`TWILIO_FROM_NUMBER`, `PUBLIC_BASE_URL`, `NURSE_SMS_NUMBER`,
`VOLUNTEER_SMS_NUMBER`. See [.env.example](.env.example).

See [DECISIONS.md](DECISIONS.md) for assumptions and anything stubbed.
