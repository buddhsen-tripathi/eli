"""Cascaded pipeline loop — the canonical per-turn ordering.

    RAW AUDIO / TEXT
        -> STT (Deepgram N-best)
        -> EMERGENCY SCREEN (rule-based, FIRST, on raw hypotheses)   [may 911]
        -> GER (hero: N-best -> repaired transcript + confidence)
        -> EMERGENCY RE-SCREEN (on repaired text)                    [may 911]
        -> SUPERVISOR (constrained state machine; never diagnoses)
             |-- red-flag engine (rule-based) -> ESCALATE + SMS
             '-- safety gate on every candidate line (inside supervisor)
        -> TTS (Cartesia slow preset) / spoken line

This module is transport-agnostic: it works on a wav-bytes turn (phone/mic) or a
text turn (simulator without audio). The Twilio webhook reimplements the same
ordering inline in twilio_voice.py to fit the request/response TwiML shape; this
loop is the reference + the simulator engine.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from sentinelcall.agent import inbound as inbound_qa
from sentinelcall.agent.supervisor import Supervisor, SupervisorTurn
from sentinelcall.data.record import Patient, append_call_record
from sentinelcall.obs import trace as _trace
from sentinelcall.pipeline import emergency, ger as ger_stage
from sentinelcall.pipeline.emergency import EMERGENCY_SCRIPT
from sentinelcall.telephony import twilio_sms


@dataclass
class TurnOutcome:
    reply: str
    emergency: bool = False
    escalated: bool = False
    ended: bool = False
    ger_confidence: Optional[float] = None
    repaired: Optional[str] = None


class ConversationEngine:
    """Drives one call (outbound state machine or inbound Q&A) turn by turn."""

    def __init__(self, patient: Patient, *, direction: str = "outbound") -> None:
        self.patient = patient
        self.direction = direction
        self.supervisor = Supervisor(patient, direction=direction) if direction == "outbound" else None
        self.ended = False

    def opening_line(self) -> str:
        if self.direction == "outbound" and self.supervisor:
            return self.supervisor.greeting()
        return (
            f"Hello {self.patient.preferred_name}, this is SentinelCall. If this "
            "is an emergency, please hang up and call 9 1 1. Otherwise, what can "
            "I help you with today?"
        )

    def process_hypotheses(self, hyps: List[str]) -> TurnOutcome:
        """Run one turn from ASR N-best hypotheses (the real path)."""
        if not hyps:
            return TurnOutcome(reply="I'm sorry, I didn't catch that. Could you say it again?")

        # 1) EMERGENCY SCREEN FIRST — on raw hypotheses, pre-LLM.
        emerg = emergency.screen_many(hyps)
        if emerg.is_emergency:
            _trace.line("EMERGENCY", f"TRIGGER: {emerg.trigger} :: {emerg.matched_text!r}", _trace.RED)
            self._fire_emergency_alert()
            self.ended = True
            return TurnOutcome(reply=EMERGENCY_SCRIPT, emergency=True, ended=True)

        # 2) GER (hero)
        ctx = {
            "surgery": self.patient.surgery,
            "post_op_day": self.patient.post_op_day,
            "state": self.supervisor.state.value if self.supervisor else "inbound",
        }
        g = ger_stage.correct(hyps, ctx)

        # 3) EMERGENCY RE-SCREEN on the repaired text.
        emerg2 = emergency.screen(g.repaired)
        if emerg2.is_emergency:
            _trace.line("EMERGENCY", f"TRIGGER (post-GER): {emerg2.trigger}", _trace.RED)
            self._fire_emergency_alert()
            self.ended = True
            return TurnOutcome(reply=EMERGENCY_SCRIPT, emergency=True, ended=True)

        # 4) SUPERVISOR + safety gate (gate is applied inside the supervisor).
        if self.direction == "inbound":
            turn = inbound_qa.answer(self.patient, g.repaired)
            if turn.escalate and turn.escalation:
                twilio_sms.escalate(self.patient, turn.escalation, patient_words=g.repaired)
            return TurnOutcome(reply=turn.reply, escalated=turn.escalate,
                               ger_confidence=g.confidence, repaired=g.repaired)
        else:
            sup = self.supervisor
            turn: SupervisorTurn = sup.handle(
                g.repaired,
                ger_confidence=g.confidence,
                ger_needs_readback=g.needs_readback,
                readback_prompt=g.readback_prompt,
            )
            if turn.escalate and turn.escalation:
                twilio_sms.escalate(self.patient, turn.escalation, patient_words=g.repaired)
            if turn.ended:
                self._finalize()
            return TurnOutcome(reply=turn.reply, escalated=turn.escalate,
                               ended=turn.ended, ger_confidence=g.confidence, repaired=g.repaired)

    def process_text(self, text: str) -> TurnOutcome:
        """Convenience path when there's no audio (single 'hypothesis'). GER
        still runs — it repairs even a single garbled string."""
        return self.process_hypotheses([text])

    # ---- internals ----

    def _fire_emergency_alert(self) -> None:
        from sentinelcall.agent.redflags import RedFlag, RedFlagResult, Route

        flags = RedFlagResult(flags=[
            RedFlag("emergency_911",
                    "Emergency phrase detected on call; patient told to call 911.",
                    Route.EMERGENCY, clinical=True)
        ])
        try:
            twilio_sms.escalate(self.patient, flags, patient_words="[emergency screen triggered]")
        except Exception as exc:
            _trace.event("emergency.alert_error", error=repr(exc))

    def _finalize(self) -> None:
        if self.ended:
            return
        self.ended = True
        if self.supervisor:
            try:
                append_call_record(self.supervisor.extract, timestamp=None)
            except Exception as exc:
                _trace.event("finalize.error", error=repr(exc))
