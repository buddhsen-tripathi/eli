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
from typing import Dict, Optional
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
from sentinelcall.obs import trace as _trace
from sentinelcall.pipeline import emergency
from sentinelcall.pipeline.emergency import EMERGENCY_SCRIPT
from sentinelcall.telephony import twilio_sms


# ---------------------------------------------------------------------------
# TwiML helpers (slow, clear, elderly-friendly voice)
# ---------------------------------------------------------------------------

# Twilio Amazon Polly neural voice; slow prosody via SSML <prosody rate>.
_VOICE = "Polly.Joanna-Neural"


def _say(text: str) -> str:
    # Slow the cadence for age-related hearing decline (design choice).
    safe = escape(text)
    return (
        f'<Say voice="{_VOICE}"><prosody rate="85%">{safe}</prosody></Say>'
    )


def _twiml(*inner: str) -> str:
    return '<?xml version="1.0" encoding="UTF-8"?><Response>' + "".join(inner) + "</Response>"


def _record_turn(action_url: str, *, prompt: Optional[str] = None) -> str:
    """Speak an optional prompt, then record the patient's reply (their turn)."""
    parts = []
    if prompt:
        parts.append(_say(prompt))
    parts.append(
        f'<Record action="{action_url}" method="POST" maxLength="8" '
        f'timeout="3" playBeep="false" trim="trim-silence" />'
    )
    # If they say nothing, gently re-prompt via the same action (Twilio posts
    # with an empty RecordingUrl handled by the webhook).
    return _twiml(*parts)


def _hangup(text: str) -> str:
    return _twiml(_say(text), "<Hangup/>")


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


_SESSIONS: Dict[str, CallSession] = {}


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
            return _record_turn(_abs_url(f"/voice/turn?sid={call_sid}"),
                                prompt="I'm sorry, I didn't catch that. Could you say it again?")

        # 2) Emergency screen FIRST on the RAW hypotheses (pre-LLM).
        emerg = emergency.screen_many(hyps)
        if emerg.is_emergency:
            _trace.line("EMERGENCY", f"TRIGGER: {emerg.trigger} :: {emerg.matched_text!r}", _trace.RED)
            _fire_emergency_alert(session)
            return _hangup(EMERGENCY_SCRIPT)

        # 3) GER (hero)
        ctx = {
            "surgery": patient.surgery,
            "post_op_day": patient.post_op_day,
            "state": session.supervisor.state.value if session.supervisor else "",
        }
        g = ger_stage.correct(hyps, ctx)

        # 4) Emergency re-screen on the REPAIRED text (in case GER surfaced it).
        emerg2 = emergency.screen(g.repaired)
        if emerg2.is_emergency:
            _trace.line("EMERGENCY", f"TRIGGER (post-GER): {emerg2.trigger}", _trace.RED)
            _fire_emergency_alert(session)
            return _hangup(EMERGENCY_SCRIPT)

        # 5) Supervisor (inbound Q&A vs outbound state machine)
        if session.direction == "inbound":
            turn = inbound_qa.answer(patient, g.repaired)
            if turn.escalate and turn.escalation:
                twilio_sms.escalate(patient, turn.escalation, patient_words=g.repaired)
            reply = turn.reply
            # inbound stays open for more questions
            return _record_turn(_abs_url(f"/voice/turn?sid={call_sid}"), prompt=reply)
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
                return _hangup(turn.reply)
            return _record_turn(_abs_url(f"/voice/turn?sid={call_sid}"), prompt=turn.reply)

    # ---- Outbound entrypoint (Twilio hits this when the patient answers) ----

    @app.post("/voice/outbound")
    async def voice_outbound(request: Request):
        params = dict(request.query_params)
        form = await request.form()
        call_sid = form.get("CallSid", "sim")
        patient_id = params.get("patient_id", "")
        patient = load_patient_by_id(patient_id)
        if not patient:
            return _xml(_hangup("I'm sorry, I couldn't find your record. Goodbye."))
        sup = Supervisor(patient, direction="outbound")
        _SESSIONS[call_sid] = CallSession(patient=patient, direction="outbound", supervisor=sup,
                                          greeted=True)
        greeting = sup.greeting()
        return _xml(_record_turn(_abs_url(f"/voice/turn?sid={call_sid}"), prompt=greeting))

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
            return _xml(_record_turn(_abs_url(f"/voice/turn?sid={call_sid}"), prompt=greeting))
        _SESSIONS[call_sid] = CallSession(patient=patient, direction="inbound")
        greeting = (
            f"Hello {patient.preferred_name}, this is SentinelCall. "
            "If this is an emergency, please hang up and call 9 1 1. "
            "Otherwise, what can I help you with today?"
        )
        return _xml(_record_turn(_abs_url(f"/voice/turn?sid={call_sid}"), prompt=greeting))

    # ---- Per-turn (Twilio posts the recording here) ----

    @app.post("/voice/turn")
    async def voice_turn(request: Request):
        params = dict(request.query_params)
        form = await request.form()
        call_sid = params.get("sid") or form.get("CallSid", "sim")
        session = _SESSIONS.get(call_sid)
        if not session:
            return _xml(_hangup("I'm sorry, this session has ended. Goodbye."))

        recording_url = form.get("RecordingUrl", "")
        if not recording_url:
            # No speech captured — gentle re-prompt.
            return _xml(_record_turn(_abs_url(f"/voice/turn?sid={call_sid}"),
                                     prompt="I didn't hear anything. Please tell me how you're doing."))
        wav = await _download_recording(recording_url)
        if not wav:
            return _xml(_record_turn(_abs_url(f"/voice/turn?sid={call_sid}"),
                                     prompt="I'm having trouble hearing you. Could you repeat that?"))
        twiml = await _process_patient_audio(session, wav, call_sid)
        return _xml(twiml)

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
