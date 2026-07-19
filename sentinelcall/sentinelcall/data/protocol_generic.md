# Post-Op Recovery Reference Protocol — General (any surgery)

> **LAYER 2 — REFERENCE (general), FALLBACK.** Used when no surgery-specific
> protocol pack matches the patient's `surgery` field. Same rules as every
> Layer-2 doc: RAG'd to inform the agent's questions and escalation only; never
> read to the patient as a recommendation; never overrides the patient's own
> prescribed record (Layer 1). To support a new surgery type, drop a
> `protocol_<type>.md` next to this file — the loader picks the best match and
> falls back here.

## What is generally normal after surgery

- **Pain** that gradually improves day over day and is controlled by the
  prescribed medication. Some discomfort with movement and activity is expected.
- **Swelling and bruising** around the surgical site.
- **Mild warmth** over the incision that is not spreading.
- **Mild itching** as the incision heals.
- A **small amount of clear or lightly blood-tinged drainage** in the first
  24–72 hours.
- **Fatigue, disrupted sleep, and reduced appetite** in the first several days.

## Red flags — route to a nurse (never diagnosed by the agent)

### Infection signals
- **Fever of 100.4°F (38°C) or higher.**
- **Spreading redness** extending outward from the incision, growing day to day.
- **Pus, cloudy, or foul-smelling drainage.**
- **Increasing warmth with increasing pain and redness.**
- **Wound edges opening or separating.**
- Chills or feeling generally unwell alongside any of the above.

### Blood clot signals
- **New or increasing calf pain, tenderness, or swelling in one leg** — possible
  deep vein thrombosis. Route to clinical review.
- **Sudden shortness of breath or chest pain** — EMERGENCY, instruct 911.

### Pain / medication signals
- **Pain rated 8 or higher** not controlled by the prescribed regimen, or pain
  suddenly much worse than the day before.
- **Medication confusion** — double-dosing, mixing medications, or missing
  prescribed doses. Route to nurse/pharmacy.

### Falls and cognition
- **Any fall or near-fall.**
- New **confusion, disorientation, or "seems off today"** reported by patient or
  caregiver — possible delirium; warrants a nurse assessment.

## Emergency — instruct 911 immediately (pre-LLM screen handles these)

- Chest pain or pressure.
- Trouble breathing / shortness of breath.
- Uncontrolled bleeding that will not stop with pressure.
- A fall in which the patient cannot get up or may have hit their head.
- Sudden weakness, face drooping, or slurred speech (possible stroke).

## General orientation

- **First 72 hours:** pain control, rest, gentle prescribed movement. Drainage
  and swelling expected; they should be decreasing, not increasing.
- **First two weeks:** gradually increasing activity per discharge instructions.
  Redness should not spread; fever, spreading redness, and new calf pain are
  never normal.
- **Beyond two weeks:** continued healing and strengthening. Escalate any new
  infection, clot, or fall signal regardless of how far out the patient is.
