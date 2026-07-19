# DECISIONS.md

Assumptions, trade-offs, and stubs made during the 5-hour build. Grouped by area.

## Scope

- **General post-op agent, not knee-only.** The spec says "start: knee
  replacement." Knee is treated as the *first protocol pack*, and the whole
  system is surgery-agnostic: patient records carry a free-text `surgery` field,
  Layer-2 RAG selects `protocol_<type>.md` by surgery (falling back to
  `protocol_generic.md`), and the safety spine operates on phrases/fields, not on
  "knee." Seed data includes a **hip** patient (P002) that routes to the generic
  protocol, to prove generality on stage.

## Platform / runtime

- **Python 3.11** (via Homebrew), not the system 3.9.6. The Deepgram v3 SDK uses
  `match` statements (3.10+); the newer Deepgram v6 SDK has a reworked, less-
  documented API. Pinning **`deepgram-sdk>=3,<4` on Python 3.11** gives the
  well-documented prerecorded API with `alternatives=N` (N-best) that GER needs.
- **Keys reused from the local MIRA repo** (`~/Desktop/M.I.R.A-main/.env`) for
  the demo: Anthropic, Deepgram, Cartesia. `.env` is gitignored; key values were
  never printed. No OpenAI key present → the Whisper STT fallback is unused (not
  needed; Deepgram is the primary and is working).

## LLM

- **Claude via `SUPERVISOR_MODEL` / `GER_MODEL` = `claude-sonnet-4-6`**,
  temperature **0.25** per spec. The gateway dispatches by model-name prefix
  (`claude-` → Anthropic). If that model id isn't enabled on the account, change
  the two env vars to an available Sonnet-class id — nothing else changes.
- **The LLM never decides escalation and never generates a dose.** Red-flag
  detection is rule/threshold-based (`agent/redflags.py`); doses are quoted
  verbatim from Layer 1. The LLM only shapes tone and extracts structured fields,
  and every line it produces passes the safety gate.

## STT (N-best)

- **Default model is `enhanced`, not `nova-2`.** Deepgram's `nova-2`/`nova-3`
  reject `alternatives>1` with a 400 ("Nova-2 models do not support more than one
  alternative") — which would silently kill GER. `enhanced` (also `nova`, `base`)
  supports N-best. `stt.py` auto-substitutes an N-best-capable model if a
  non-capable one is configured, and falls back to a single alternative as a last
  resort. **This bug would have broken the hero live** — caught and guarded.
- On clean audio the N-best alternatives are near-identical (expected); diversity
  emerges on degraded/elderly speech, which is the real use case.

## TTS

- **Cartesia `sonic-2`, `speed="slow"`** for age-related hearing decline (a
  stated design choice). Non-streaming WAV bytes are used (simpler); the phone
  path streams via Twilio regardless. Local audio *playback* in the simulator
  needs `sounddevice` (optional extra) — without it, `--audio` still does the
  real TTS→STT round-trip, it just doesn't play through speakers.

## Telephony (Twilio)

- **Patient turns use `<Record>` (not `<Gather input="speech">`).** `<Gather>`
  returns a *single* Twilio transcript, discarding the N-best that GER needs. So
  we record a short clip, download it, and run our own Deepgram-N-best → GER
  pipeline — **keeping the hero live on a real phone call.** Trade-off: one round
  of record→download→transcribe adds latency vs. streaming. Acceptable for a
  demo; a production build would bridge the Twilio Media Stream over WebSocket to
  a streaming STT (the correct but much heavier path — deliberately deferred).
- **Speaking uses Twilio `<Say>` (Amazon Polly neural) with SSML
  `prosody rate=85%`**, not Cartesia `<Play>` — zero extra audio hosting, works
  immediately. Swapping in hosted Cartesia audio is a one-line change if
  `PUBLIC_BASE_URL` serves the files.
- **Per-call state is in-memory** keyed by Twilio `CallSid`. Fine for a single
  server / demo; a production build would use a shared store.
- **If Twilio isn't configured, SMS is simulated** — the exact nurse/volunteer
  message is rendered to the console/trace so the escalation is still visible.
  Voice requires real Twilio + a public URL; the local **simulator** (`sentinel
  sim` / `sentinel demo`) exercises the identical pipeline without a phone, which
  is what protects the demo if carrier audio is flaky. **The finale is a real
  dialable call.**
- Webhook `action` URLs are absolute when `PUBLIC_BASE_URL` is set; if left blank
  they're relative and Twilio resolves them against the request host, so `serve`
  still works locally for testing.

## Safety / clinical

- **Emergency screen is pure regex, pre-LLM, and runs on the raw N-best AND the
  repaired transcript** — so a bad transcription can't hide an emergency, and a
  GER repair that *surfaces* one is also caught. Patterns require the dangerous
  *combination* (e.g. "chest" + pain/pressure), tuned to survive light mis-
  transcription, and were tested against false-positive guards (warm room, ice-
  pack redness, warm blanket → no trigger).
- **Safety gate blocks by rule** (diagnosis/reassurance/treatment/ungrounded
  dose) and, on a block, falls back to the safe state template rather than ever
  speaking the blocked line. Grounding check: any `NN mg` in a candidate must
  appear in the patient's verbatim Layer-1 instructions.
- **Red-flag patterns were broadened after testing** ("redness around my incision
  is spreading", "calf is really swollen", "feel warm" in wound context) because
  the first pass produced dangerous false *negatives*. Erring toward flagging is
  intentional (negative-confirmation discipline).

## Stubbed / simplified (explicitly)

- **Per-patient acoustic baseline (Mechanism 1)** is described in the spec but
  not implemented — it needs multiple prior calls to establish. GER + confidence-
  gated read-back (Mechanisms 2 & 3) are the parts that matter for the demo and
  are fully implemented.
- **Layer-2 RAG is keyword-overlap**, not embeddings. Deliberately not over-
  engineered for the demo; the `ReferenceRAG.retrieve()` interface is unchanged
  if embeddings are swapped in later. Retrieval is intentionally coarse — it
  *informs* the agent, and is never spoken verbatim to the patient.
- **Trend logic** over Layer-3 (`call_history`) is stored but not yet computed
  into cross-call deltas; the structured extracts are appended so a clinician
  view can trend them.
- **PII redaction before the model boundary** (a stated compliance goal) is not
  implemented for the hackathon — the demo uses synthetic patients. It's the
  first thing a production build adds.
- **No auth on the webhook server** (loopback/ngrok demo trust model). Twilio
  request signature validation would be added for production.

## Reuse from MIRA

- **Taken (forked in shape):** the provider-agnostic LLM gateway (model-by-prefix
  dispatch, Anthropic adapter with prompt caching, cost metering), the STT/TTS
  provider shapes (Deepgram + Cartesia), and the tracing/obs pattern.
- **Left (not ported):** all SwiftUI/macOS UI, wake-word + speech monitor (a
  phone call *is* the session), media-key stack, the browser/commerce/device
  specialists, and MIRA's "capable & autonomous" supervisor philosophy —
  SentinelCall's supervisor is the **opposite**: maximally constrained.
