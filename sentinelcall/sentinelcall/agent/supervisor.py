"""Supervisor — the CONSTRAINED state machine (opposite of MIRA's autonomous one).

Design pressure is inverted from MIRA: MIRA's supervisor was maximally capable
and autonomous. SentinelCall's supervisor is maximally CONSTRAINED. It:

  * never diagnoses, never advises treatment, never computes a dose;
  * uses Claude ONLY to shape TONE and extract structured fields — never to
    decide whether something is a red flag (that's the rule-based engine) and
    never to generate a dose (that's a verbatim Layer-1 quote);
  * routes every candidate line through the safety gate before it can be spoken;
  * honors negative-confirmation: low-confidence on a safety-critical field
    escalates or reads back — it never reassures.

Per turn the supervisor receives the GER-repaired transcript (or a read-back
request) and returns a `SupervisorTurn`: the line to speak + any escalation +
the structured fields extracted this turn.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from sentinelcall.agent import redflags as rf
from sentinelcall.agent.states import STATE_PROMPTS, State, next_state
from sentinelcall.data.record import CallExtract, Patient, verbatim_med_instruction
from sentinelcall.data.reference_rag import reference_rag
from sentinelcall.gateway.llm import Message, llm
from sentinelcall.pipeline import safety_gate
from sentinelcall.obs import trace as _trace


PERSONA = (
    "You are SentinelCall, a warm, patient, unhurried recovery check-in voice "
    "for an elderly post-operative patient. Talk like a kind human nurse on the "
    "phone, not a form: use natural, everyday language ('okay', 'got it', 'no "
    "rush'), acknowledge what they just said before moving on, and ask about "
    "only ONE thing at a time. Short, gentle sentences. You are infinitely "
    "un-annoyed by repetition or confusion.\n\n"
    "ABSOLUTE RULES (these override tone every time):\n"
    "- You are a structured-intake and routing instrument, NOT a medical "
    "advisor. You NEVER diagnose, NEVER name a condition, NEVER say whether "
    "something is or isn't an infection/clot/etc.\n"
    "- You NEVER recommend, suggest, or compute a treatment or a dose. If a dose "
    "must be stated, it will be provided to you verbatim from the patient's "
    "record; quote it EXACTLY and never modify it.\n"
    "- You NEVER tell the patient they are 'fine' or that there's 'nothing to "
    "worry about'. If there is concern, you calmly say a nurse will review it "
    "and that you're connecting them.\n"
    "- You NEVER answer 'should I go to the ER?' with yes or no. You route.\n"
    "- Keep replies to 1-2 short sentences suitable for slow speech."
)


@dataclass
class SupervisorTurn:
    reply: str                       # line to speak (post safety gate)
    state: State                     # state AFTER this turn
    escalate: bool = False
    escalation: Optional[rf.RedFlagResult] = None
    fields: Dict[str, Any] = field(default_factory=dict)  # Layer-3 extracted
    ended: bool = False
    blocked_reason: Optional[str] = None  # if a candidate line was blocked


class Supervisor:
    def __init__(self, patient: Patient, *, direction: str = "outbound") -> None:
        self.patient = patient
        self.direction = direction
        self.state = State.IDENTIFY
        self.extract = CallExtract(
            patient_id=patient.patient_id,
            direction=direction,
            post_op_day=patient.post_op_day,
        )
        self._history: List[Message] = []

    # ---- helpers ----

    def _surgery_short(self) -> str:
        s = self.patient.surgery.lower()
        for key in ("knee", "hip", "shoulder", "spine", "cardiac", "cataract"):
            if key in s:
                return f"{key} surgery"
        return "surgery"

    def _fill(self, template: str) -> str:
        return template.format(
            name=self.patient.preferred_name,
            post_op_day=self.patient.post_op_day,
            surgery_short=self._surgery_short(),
            surgery=self.patient.surgery,
        )

    def _grounding_for_state(self, state: State) -> List[str]:
        """Strings the reply is allowed to quote verbatim this turn (Layer 1)."""
        if state == State.MEDS:
            return [m.get("verbatim_instruction", "") for m in self.patient.medications]
        return []

    # ---- opening line (S1 GREET) ----

    def greeting(self) -> str:
        self.state = State.GREET
        line = self._fill(STATE_PROMPTS[State.GREET])
        v = safety_gate.check(line, append_safety_net=False)
        return v.text if v.ok else line

    def inbound_greeting(self) -> str:
        """Opener when the KNOWN patient calls US. We already have their case, so
        acknowledge that, mention day + surgery so it's clearly personalized, and
        go straight into the check-in — no 'how can I help you'. Same S1 state as
        the outbound greeting; the flow proceeds identically from here."""
        self.state = State.GREET
        line = self._fill(STATE_PROMPTS[State.INBOUND_GREET])
        v = safety_gate.check(line, append_safety_net=False)
        return v.text if v.ok else line

    # ---- one patient turn ----

    def handle(
        self,
        patient_text: str,
        *,
        ger_confidence: float = 1.0,
        ger_needs_readback: bool = False,
        readback_prompt: Optional[str] = None,
    ) -> SupervisorTurn:
        """Process one repaired patient utterance in the current state.

        The emergency screen runs UPSTREAM of this (in the pipeline loop); by the
        time we're here, it's not a 911 situation.
        """
        # 1) Negative-confirmation: if GER flagged a low-confidence,
        #    safety-critical transcript, we DO NOT act on it. Read back instead.
        if ger_needs_readback and readback_prompt:
            _trace.line("SUPERVISOR", "low-confidence safety-critical -> read-back (no action)",
                        _trace.YELLOW)
            v = safety_gate.check(readback_prompt, append_safety_net=False)
            return SupervisorTurn(reply=v.text, state=self.state, fields={})

        # 2) Rule-based red-flag detection (NOT the LLM). This is what decides
        #    escalation — the model never gets to talk a red flag away.
        thresh = self.patient.red_flag_thresholds.get("pain_scale_uncontrolled", 8)
        pain = self._extract_pain(patient_text)
        flags = rf.detect(patient_text, pain=pain, pain_threshold=int(thresh))

        # 3) Extract structured Layer-3 fields for this state.
        self._update_extract(patient_text, pain=pain, flags=flags)

        if flags.has_clinical or (flags.flags and flags.route == rf.Route.VOLUNTEER):
            # Divert to ESCALATE. The spoken line is a calm, NON-diagnostic
            # instruction; escalation SMS is fired by the loop/telephony layer.
            return self._escalate_turn(flags)

        # 4) Normal path: advance state, generate the next probe (tone via LLM,
        #    bounded), quoting verbatim doses when in MEDS.
        nxt = next_state(self.state)
        reply = self._compose_reply(nxt, patient_text)
        self.state = nxt
        ended = nxt == State.CLOSE
        grounding = self._grounding_for_state(nxt)
        v = safety_gate.check(reply, grounding=grounding)
        if not v.ok:
            # A generated line failed the gate -> never speak it. Fall back to
            # the safe template for the state and re-gate.
            _trace.line("SAFETY-GATE", f"BLOCKED ({v.category}): {v.violations}", _trace.RED)
            fallback = self._fill(STATE_PROMPTS.get(nxt, STATE_PROMPTS[State.CLOSE]))
            v = safety_gate.check(fallback, grounding=grounding)
        return SupervisorTurn(
            reply=v.text, state=self.state, fields=self.extract.to_dict(),
            ended=ended, blocked_reason=(None if v.ok else "unrecoverable"),
        )

    # ---- ESCALATE (S6) ----

    def _escalate_turn(self, flags: rf.RedFlagResult) -> SupervisorTurn:
        self.state = State.ESCALATE
        self.extract.escalated = True
        self.extract.red_flags = flags.labels
        self.extract.escalation_channel = flags.route.value

        clinical = flags.has_clinical
        if clinical:
            line = (
                f"Thank you for telling me, {self.patient.preferred_name}. "
                "I want a nurse to take a look at this. I'm connecting your "
                "care team now, and someone will reach out to you shortly."
            )
        else:
            line = (
                f"Thank you for letting me know, {self.patient.preferred_name}. "
                "I'll arrange for someone to check in on you and help."
            )
        _trace.line("SUPERVISOR", f"ESCALATE -> {flags.route.value} :: {flags.labels}",
                    _trace.RED if clinical else _trace.BLUE)
        v = safety_gate.check(line)
        return SupervisorTurn(
            reply=v.text, state=self.state, escalate=True, escalation=flags,
            fields=self.extract.to_dict(),
        )

    # ---- reply composition (bounded LLM for tone only) ----

    def _compose_reply(self, target_state: State, patient_text: str) -> str:
        """Ask Claude to phrase the NEXT probe warmly, but the CONTENT is fixed
        by the template + (for MEDS) verbatim doses. If the LLM is unavailable,
        the template is spoken as-is."""
        template = STATE_PROMPTS.get(target_state)
        if template is None:
            return self._fill(STATE_PROMPTS[State.CLOSE])
        base = self._fill(template)

        # For MEDS, inject the verbatim instructions the model MUST quote.
        verbatim_block = ""
        if target_state == State.MEDS:
            meds = self.patient.medications
            lines = [f'- {m["name"]}: "{m["verbatim_instruction"]}"' for m in meds]
            verbatim_block = (
                "\n\nThe patient's prescribed instructions (quote any dose "
                "EXACTLY, do not change numbers):\n" + "\n".join(lines)
            )

        try:
            sys = PERSONA
            user = (
                f"Patient just said: \"{patient_text}\".\n"
                f"Your next goal (state {target_state.value}) is to say, warmly "
                f"and slowly, the equivalent of:\n\"{base}\"{verbatim_block}\n\n"
                "Rewrite ONLY for warmth and natural flow. Keep it to 1-2 short "
                "sentences. Do NOT add medical opinions, reassurance, or advice. "
                "Return just the spoken line, no quotes."
            )
            resp = llm().complete(
                [Message(role="system", content=sys), Message(role="user", content=user)],
                max_tokens=160,
            )
            text = (resp.text or "").strip().strip('"')
            return text or base
        except Exception as exc:
            _trace.event("supervisor.compose_error", error=repr(exc))
            return base

    # ---- Layer-3 extraction ----

    def _extract_pain(self, text: str) -> Optional[int]:
        import re

        m = re.search(r"\b(?:pain(?:\s+is)?|rate[d]?\s+it|it'?s|about|a)\s*(?:a\s+)?(\d{1,2})\b", text.lower())
        if not m:
            m = re.search(r"\b(\d{1,2})\s*(?:out of|/)\s*(?:10|ten)\b", text.lower())
        if m:
            try:
                val = int(m.group(1))
                if 0 <= val <= 10:
                    return val
            except ValueError:
                pass
        # word numbers
        words = {"zero":0,"one":1,"two":2,"three":3,"four":4,"five":5,"six":6,
                 "seven":7,"eight":8,"nine":9,"ten":10}
        for w, n in words.items():
            if re.search(rf"\bpain\b.*\b{w}\b|\b{w}\s+out of\s+ten\b", text.lower()):
                return n
        return None

    def _update_extract(self, text: str, *, pain: Optional[int], flags: rf.RedFlagResult) -> None:
        low = text.lower()
        if pain is not None:
            self.extract.pain = pain
        if self.state in (State.CHECKIN, State.GREET):
            if any(w in low for w in ("sleep", "slept", "insomnia", "awake")):
                self.extract.sleep = "poor" if any(
                    w in low for w in ("bad", "poor", "not", "cant", "can't", "hardly", "awake")
                ) else "good"
            if any(w in low for w in ("eat", "appetite", "hungry", "food")):
                self.extract.appetite = "reduced" if any(
                    w in low for w in ("not", "no", "cant", "can't", "little", "hardly")
                ) else "normal"
        if self.state == State.MEDS:
            if any(f.label == "med_confusion" for f in flags.flags):
                self.extract.meds_adherent = False
            elif any(w in low for w in ("yes", "taking", "took them", "on schedule")):
                self.extract.meds_adherent = True
        if self.state == State.WOUND:
            if any(f.label in ("infection",) for f in flags.flags):
                self.extract.wound_status = "red_flag"
            elif any(w in low for w in ("fine", "okay", "good", "normal", "healing")):
                self.extract.wound_status = "normal"
        if any(f.label == "fever" for f in flags.flags):
            self.extract.fever = True
        if any(f.label == "fall" for f in flags.flags):
            self.extract.fall = True
        if any(f.label == "confusion" for f in flags.flags):
            self.extract.confusion_signal = True
        # accumulate notes (bounded)
        if text and len(self.extract.notes) < 800:
            self.extract.notes = (self.extract.notes + " | " + text).strip(" |")
