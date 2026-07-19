"""Twilio Voice — outbound call + inbound webhook, with a recording->GER bridge.

Two design notes for the phone path:

1. GER on the phone. Twilio's built-in <Gather input="speech"> returns a SINGLE
   transcript — which throws away the N-best hypotheses GER needs. So for
   patient turns we use <Record> (short, ~6s), download the recording, and run
   it through OUR pipeline (Deepgram N-best -> GER -> supervisor -> safety
   gate). This keeps the hero live on a real call. A <Gather> fast-path is kept
   for latency-sensitive confirmations.

2. Speaking. We default to Twilio <Say> (zero extra hosting) with a slow,
   clear voice. Cartesia audio can be swapped in via <Play> if PUBLIC_BASE_URL
   hosts the synthesized files; not required for the demo.

The webhook is a small FastAPI app. Per-call state (patient, supervisor,
direction) lives in an in-memory session map keyed by Twilio CallSid.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Dict, Optional
from xml.sax.saxutils import escape

# Imported at module scope so FastAPI can resolve the `Request` annotation on
# the webhook handlers (see note in build_app). Guarded so the package still
# imports for the simulator if fastapi isn't installed.
try:
    from fastapi import Request
except Exception:  # pragma: no cover
    Request = object  # type: ignore

from sentinelcall.agent.supervisor import Supervisor
from sentinelcall.agent import inbound as inbound_qa
from sentinelcall.agent.states import State
from sentinelcall.config import get_settings
from sentinelcall.data.record import (
    Patient,
    append_call_record,
    guest_patient,
    load_patient_by_id,
    load_patient_by_phone,
)
from pathlib import Path as _Path

from sentinelcall.obs import trace as _trace
from sentinelcall.pipeline import emergency
from sentinelcall.pipeline.emergency import EMERGENCY_SCRIPT
from sentinelcall.telephony import twilio_sms


# ---------------------------------------------------------------------------
# TwiML helpers (slow, clear, elderly-friendly voice)
# ---------------------------------------------------------------------------

# Twilio Amazon Polly neural voice; slow prosody via SSML <prosody rate>.
# This is the FALLBACK voice — used when Cartesia synth is unavailable/failing.
_VOICE = "Polly.Joanna-Neural"


def _say_polly(text: str) -> str:
    """Fallback: Twilio-native speech (Polly), slowed for elderly hearing."""
    safe = escape(text)
    return f'<Say voice="{_VOICE}"><prosody rate="85%">{safe}</prosody></Say>'


# ---- Cartesia audio hosting (the real voice on the phone) ------------------
#
# Twilio <Play> needs a fetchable audio URL. We synthesize each spoken line with
# Cartesia, downsample to 8 kHz mono WAV (telephone band — smaller + universally
# playable by Twilio), cache it in memory by content hash, and serve it at
# /audio/<hash>.wav. If Cartesia (or PUBLIC_BASE_URL) is unavailable, callers
# fall back to _say_polly so the call NEVER breaks.

_AUDIO_CACHE: Dict[str, bytes] = {}
_AUDIO_CACHE_MAX = 200  # bounded; oldest evicted


def _to_twilio_wav(wav_bytes: bytes) -> Optional[bytes]:
    """Convert Cartesia's 24 kHz PCM WAV to 8 kHz mono 16-bit WAV for Twilio.
    Returns None on any failure (caller then falls back to Polly)."""
    try:
        import audioop
        import io
        import wave

        with wave.open(io.BytesIO(wav_bytes), "rb") as w:
            n_ch, width, rate = w.getnchannels(), w.getsampwidth(), w.getframerate()
            frames = w.readframes(w.getnframes())
        if n_ch == 2:
            frames = audioop.tomono(frames, width, 0.5, 0.5)
        if width != 2:
            frames = audioop.lin2lin(frames, width, 2)
            width = 2
        if rate != 8000:
            frames, _ = audioop.ratecv(frames, width, 1, rate, 8000, None)
        out = io.BytesIO()
        with wave.open(out, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(8000)
            w.writeframes(frames)
        return out.getvalue()
    except Exception as exc:  # pragma: no cover - defensive
        _trace.event("audio.convert_error", error=repr(exc))
        return None


async def _cartesia_play_url(text: str) -> Optional[str]:
    """Synthesize `text` with Cartesia, cache the Twilio-ready WAV, and return the
    absolute /audio/<hash>.wav URL. None if synth/host isn't possible -> Polly."""
    base = (get_settings().public_base_url or "").rstrip("/")
    if not base:
        return None  # no public URL to host audio at -> can't <Play>
    from sentinelcall.pipeline.tts import tts

    try:
        raw = await tts().synthesize(text)
    except Exception as exc:
        _trace.event("audio.synth_error", error=repr(exc))
        return None
    if not raw:
        return None
    wav = _to_twilio_wav(raw)
    if not wav:
        return None
    import hashlib

    key = hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]
    if key not in _AUDIO_CACHE:
        if len(_AUDIO_CACHE) >= _AUDIO_CACHE_MAX:
            _AUDIO_CACHE.pop(next(iter(_AUDIO_CACHE)))
        _AUDIO_CACHE[key] = wav
    return f"{base}/audio/{key}.wav"


async def _say(text: str) -> str:
    """Speak a line: Cartesia <Play> if we can synth+host it, else Polly <Say>."""
    url = await _cartesia_play_url(text)
    if url:
        return f"<Play>{escape(url)}</Play>"
    return _say_polly(text)


def _twiml(*inner: str) -> str:
    return '<?xml version="1.0" encoding="UTF-8"?><Response>' + "".join(inner) + "</Response>"


async def _record_turn(action_url: str, *, prompt: Optional[str] = None) -> str:
    """Speak an optional prompt, then record the patient's reply (their turn).

    Recording params are tuned for slow, elderly speech AND to avoid capturing
    the agent's own audio:
      * A short <Pause> after the prompt lets the played audio fully finish and
        the line settle, so <Record> doesn't grab the echo/tail of our own voice
        (the cause of the "I'm doing alright. I'm doing alright." doubling).
      * maxLength=30s so a slow speaker isn't cut off mid-sentence.
      * timeout=5s of trailing silence ends the turn (patients pause to think;
        3s cut them off).
      * playBeep=true gives an audible "your turn" cue for elderly callers.
    """
    parts = []
    if prompt:
        parts.append(await _say(prompt))
    # Let our audio finish and the line go quiet before we start listening.
    parts.append('<Pause length="1"/>')
    parts.append(
        f'<Record action="{action_url}" method="POST" maxLength="30" '
        f'timeout="5" playBeep="true" trim="trim-silence" finishOnKey="" />'
    )
    # If they say nothing, gently re-prompt via the same action (Twilio posts
    # with an empty RecordingUrl handled by the webhook).
    return _twiml(*parts)


async def _hangup(text: str) -> str:
    return _twiml(await _say(text), "<Hangup/>")


# ---------------------------------------------------------------------------
# Per-call session state
# ---------------------------------------------------------------------------


@dataclass
class CallSession:
    patient: Patient
    direction: str  # outbound | inbound
    supervisor: Optional[Supervisor] = None
    greeted: bool = False
    ended: bool = False
    # Live pipeline snapshot for the dashboard ribbon (latest turn only).
    last_asr: Optional[str] = None
    last_ger: Optional[str] = None
    last_ger_conf: Optional[float] = None
    last_ger_changed: bool = False
    last_agent_line: Optional[str] = None
    turns: int = 0


_SESSIONS: Dict[str, CallSession] = {}


def _load_dashboard_html() -> str:
    try:
        return (_Path(__file__).parent / "dashboard.html").read_text(encoding="utf-8")
    except Exception:
        return "<h1>SentinelCall</h1><p>Dashboard template missing.</p>"


_DASHBOARD_HTML = _load_dashboard_html()


def _live_call_state() -> Optional[Dict[str, Any]]:
    """Snapshot of an in-progress call for the dashboard's live ribbon. Returns
    the most recently active non-ended session, or None if the line is quiet."""
    for sid, s in reversed(list(_SESSIONS.items())):
        if s.ended:
            continue
        return {
            "call_sid": sid,
            "patient_id": s.patient.patient_id,
            "patient_name": s.patient.preferred_name,
            "direction": s.direction,
            "state": s.supervisor.state.value if s.supervisor else "INBOUND_QA",
            "turns": s.turns,
            "asr": s.last_asr,
            "ger": s.last_ger,
            "ger_confidence": s.last_ger_conf,
            "ger_changed": s.last_ger_changed,
            "agent_line": s.last_agent_line,
        }
    return None


def _abs_url(path: str) -> str:
    base = (get_settings().public_base_url or "").rstrip("/")
    return f"{base}{path}"


# ---------------------------------------------------------------------------
# Outbound placement
# ---------------------------------------------------------------------------


def place_outbound_call(patient_id: str) -> str:
    """Place an outbound call to a patient. Returns the Twilio Call SID.
    Requires Twilio config + PUBLIC_BASE_URL reachable by Twilio."""
    settings = get_settings()
    settings.require("twilio_account_sid", "twilio_auth_token", "twilio_from_number",
                     "public_base_url")
    patient = load_patient_by_id(patient_id)
    if not patient:
        raise RuntimeError(f"Unknown patient_id {patient_id!r}")

    from twilio.rest import Client

    client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
    call = client.calls.create(
        to=patient.phone,
        from_=settings.twilio_from_number,
        url=_abs_url(f"/voice/outbound?patient_id={patient_id}"),
        method="POST",
    )
    _trace.line("TWILIO", f"outbound call -> {patient.phone} (patient {patient_id}) sid={call.sid}",
                _trace.CYAN)
    return call.sid


# ---------------------------------------------------------------------------
# Recording download + our-pipeline transcription (Deepgram N-best -> GER)
# ---------------------------------------------------------------------------


async def _download_recording(recording_url: str) -> bytes:
    """Download a Twilio recording as WAV bytes (auth required)."""
    settings = get_settings()
    import httpx

    url = recording_url
    if not url.endswith(".wav"):
        url = url + ".wav"
    auth = (settings.twilio_account_sid, settings.twilio_auth_token)
    async with httpx.AsyncClient(timeout=15.0) as client:
        # Twilio recordings can 404 briefly right after the call; retry a little.
        for _ in range(5):
            r = await client.get(url, auth=auth)
            if r.status_code == 200 and r.content:
                return r.content
            await asyncio.sleep(0.6)
    return b""


# ---------------------------------------------------------------------------
# FastAPI app (inbound + outbound webhooks)
# ---------------------------------------------------------------------------


def build_app():
    # NOTE: with `from __future__ import annotations`, FastAPI resolves the
    # `request: Request` annotation via get_type_hints against MODULE globals.
    # So `Request` (and friends) must be importable at module scope, not just
    # inside this function — otherwise FastAPI can't resolve the string
    # "Request" and mis-treats it as a required query param (422).
    from fastapi import FastAPI
    from fastapi.responses import PlainTextResponse

    # Import here to avoid a hard dependency when only running the simulator.
    from sentinelcall.pipeline import ger as ger_stage
    from sentinelcall.pipeline.stt import stt

    app = FastAPI(title="SentinelCall Telephony")

    def _xml(body: str) -> PlainTextResponse:
        return PlainTextResponse(content=body, media_type="application/xml")

    async def _process_patient_audio(session: CallSession, wav: bytes, call_sid: str) -> str:
        """Shared per-turn pipeline for a recorded patient utterance:
        STT N-best -> emergency screen -> GER -> emergency re-screen -> supervisor
        -> safety gate (inside supervisor) -> TwiML."""
        patient = session.patient
        # 1) STT N-best
        stt_res = await stt().transcribe(wav)
        hyps = stt_res.hypotheses
        _trace.line("STT", f"{stt_res.provider} {len(hyps)} hyps conf={stt_res.top_confidence}",
                    _trace.CYAN)

        if not hyps:
            return await _record_turn(_abs_url(f"/voice/turn?sid={call_sid}"),
                                      prompt="I'm sorry, I didn't catch that. Could you say it again?")

        # 2) Emergency screen FIRST on the RAW hypotheses (pre-LLM).
        emerg = emergency.screen_many(hyps)
        if emerg.is_emergency:
            _trace.line("EMERGENCY", f"TRIGGER: {emerg.trigger} :: {emerg.matched_text!r}", _trace.RED)
            _fire_emergency_alert(session)
            return await _hangup(EMERGENCY_SCRIPT)

        # 3) GER (hero)
        ctx = {
            "surgery": patient.surgery,
            "post_op_day": patient.post_op_day,
            "state": session.supervisor.state.value if session.supervisor else "",
        }
        g = ger_stage.correct(hyps, ctx)

        # Snapshot the live pipeline for the dashboard ribbon.
        session.turns += 1
        session.last_asr = hyps[0] if hyps else None
        session.last_ger = g.repaired
        session.last_ger_conf = g.confidence
        session.last_ger_changed = g.changed

        # 4) Emergency re-screen on the REPAIRED text (in case GER surfaced it).
        emerg2 = emergency.screen(g.repaired)
        if emerg2.is_emergency:
            _trace.line("EMERGENCY", f"TRIGGER (post-GER): {emerg2.trigger}", _trace.RED)
            _fire_emergency_alert(session)
            return await _hangup(EMERGENCY_SCRIPT)

        # 5) Supervisor (inbound Q&A vs outbound state machine)
        if session.direction == "inbound":
            turn = inbound_qa.answer(patient, g.repaired)
            if turn.escalate and turn.escalation:
                twilio_sms.escalate(patient, turn.escalation, patient_words=g.repaired)
            reply = turn.reply
            # inbound stays open for more questions
            return await _record_turn(_abs_url(f"/voice/turn?sid={call_sid}"), prompt=reply)
        else:
            sup = session.supervisor
            turn = sup.handle(
                g.repaired,
                ger_confidence=g.confidence,
                ger_needs_readback=g.needs_readback,
                readback_prompt=g.readback_prompt,
            )
            if turn.escalate and turn.escalation:
                twilio_sms.escalate(patient, turn.escalation, patient_words=g.repaired)
            if turn.ended:
                _finalize(session)
                return await _hangup(turn.reply)
            return await _record_turn(_abs_url(f"/voice/turn?sid={call_sid}"), prompt=turn.reply)

    # ---- Outbound entrypoint (Twilio hits this when the patient answers) ----

    @app.post("/voice/outbound")
    async def voice_outbound(request: Request):
        params = dict(request.query_params)
        form = await request.form()
        call_sid = form.get("CallSid", "sim")
        patient_id = params.get("patient_id", "")
        patient = load_patient_by_id(patient_id)
        if not patient:
            return _xml(await _hangup("I'm sorry, I couldn't find your record. Goodbye."))
        sup = Supervisor(patient, direction="outbound", fast_mode=True)
        _SESSIONS[call_sid] = CallSession(patient=patient, direction="outbound", supervisor=sup,
                                          greeted=True)
        greeting = sup.greeting()
        return _xml(await _record_turn(_abs_url(f"/voice/turn?sid={call_sid}"), prompt=greeting))

    # ---- Inbound entrypoint (patient calls the Twilio number) ----

    @app.post("/voice/inbound")
    async def voice_inbound(request: Request):
        form = await request.form()
        call_sid = form.get("CallSid", "sim")
        from_number = form.get("From", "")
        patient = load_patient_by_phone(from_number)
        if not patient:
            # Unknown caller (e.g. a judge dialing the demo line): DON'T hang up.
            # Fall back to a record-less guest so the caller still gets the full
            # emergency-safe pipeline + general Q&A — just no personalization and
            # no access to any real patient's clinical data.
            _trace.line("INBOUND", f"unknown caller {from_number!r} -> guest path",
                        _trace.YELLOW)
            patient = guest_patient(from_number)
            _SESSIONS[call_sid] = CallSession(patient=patient, direction="inbound")
            greeting = (
                "Hello, this is SentinelCall, the post-operative check-in line. "
                "If this is an emergency, please hang up and call 9 1 1. "
                "I don't have a record for this number, but I can still help with "
                "general recovery questions. What can I help you with today?"
            )
            return _xml(await _record_turn(_abs_url(f"/voice/turn?sid={call_sid}"), prompt=greeting))
        # KNOWN patient calling in: we already have their case. Don't ask "how can
        # I help" — drive the same structured recovery check-in as an outbound
        # call, just opened for an inbound context. The supervisor state machine
        # (S1..S7) handles the flow; red flags still escalate.
        _trace.line("INBOUND", f"known patient {patient.patient_id} -> driven check-in",
                    _trace.GREEN)
        sup = Supervisor(patient, direction="outbound", fast_mode=True)
        _SESSIONS[call_sid] = CallSession(patient=patient, direction="outbound",
                                          supervisor=sup, greeted=True)
        greeting = sup.inbound_greeting()
        return _xml(await _record_turn(_abs_url(f"/voice/turn?sid={call_sid}"), prompt=greeting))

    # ---- Per-turn (Twilio posts the recording here) ----

    @app.post("/voice/turn")
    async def voice_turn(request: Request):
        params = dict(request.query_params)
        form = await request.form()
        call_sid = params.get("sid") or form.get("CallSid", "sim")
        session = _SESSIONS.get(call_sid)
        if not session:
            return _xml(await _hangup("I'm sorry, this session has ended. Goodbye."))

        recording_url = form.get("RecordingUrl", "")
        if not recording_url:
            # No speech captured — gentle re-prompt.
            return _xml(await _record_turn(_abs_url(f"/voice/turn?sid={call_sid}"),
                                           prompt="I didn't hear anything. Please tell me how you're doing."))
        wav = await _download_recording(recording_url)
        if not wav:
            return _xml(await _record_turn(_abs_url(f"/voice/turn?sid={call_sid}"),
                                           prompt="I'm having trouble hearing you. Could you repeat that?"))
        twiml = await _process_patient_audio(session, wav, call_sid)
        return _xml(twiml)

    @app.get("/audio/{key}.wav")
    async def audio(key: str):
        """Serve a cached Cartesia-synthesized line (8 kHz mono WAV) for Twilio
        <Play>. Keys are content hashes populated by _cartesia_play_url."""
        from fastapi.responses import Response

        data = _AUDIO_CACHE.get(key)
        if not data:
            return Response(status_code=404)
        return Response(content=data, media_type="audio/wav")

    # ---- Nurse triage dashboard (clinician-facing) --------------------------

    @app.get("/api/triage")
    async def api_triage():
        from sentinelcall.telephony import dashboard_api as dash

        rows = dash.triage_list()
        return {"stats": dash.dashboard_stats(rows), "patients": rows,
                "live": _live_call_state()}

    @app.get("/api/patient/{patient_id}")
    async def api_patient(patient_id: str):
        from fastapi.responses import JSONResponse
        from sentinelcall.telephony import dashboard_api as dash

        d = dash.patient_detail(patient_id)
        if not d:
            return JSONResponse({"error": "not found"}, status_code=404)
        return d

    @app.get("/api/live")
    async def api_live():
        """Current in-progress call state — powers the live pipeline ribbon."""
        return _live_call_state()

    @app.get("/")
    async def dashboard_root():
        from fastapi.responses import HTMLResponse

        return HTMLResponse(_DASHBOARD_HTML)

    @app.get("/health")
    async def health():
        return {"ok": True, "service": "sentinelcall-telephony"}

    return app


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _fire_emergency_alert(session: CallSession) -> None:
    """On an emergency, alert the nurse (clinical channel) with a 911 note."""
    from sentinelcall.agent.redflags import RedFlag, RedFlagResult, Route

    flags = RedFlagResult(flags=[
        RedFlag("emergency_911", "Emergency phrase detected on call; patient told to call 911.",
                Route.EMERGENCY, clinical=True)
    ])
    try:
        twilio_sms.escalate(session.patient, flags, patient_words="[emergency screen triggered]")
    except Exception as exc:
        _trace.event("emergency.alert_error", error=repr(exc))


def _finalize(session: CallSession) -> None:
    if session.ended:
        return
    session.ended = True
    if session.supervisor:
        try:
            append_call_record(session.supervisor.extract, timestamp=None)
        except Exception as exc:
            _trace.event("finalize.error", error=repr(exc))
