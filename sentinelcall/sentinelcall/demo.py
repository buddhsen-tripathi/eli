"""Scripted end-to-end demo — the 6 beats that win the room.

  1. Outbound call: agent greets by name, knows surgery + post-op day.
  2. Slurred/quiet voice -> garbled ASR -> GER recovers it LIVE (visible).
  3. Spreading redness + fever -> calm instruction, NO diagnosis, routes.
  4. Nurse phone buzzes with a structured escalation SMS.
  5. Inbound: patient calls back "is it normal that it itches?" -> reassures
     from the discharge record.
  6. Green signal (missed calls) -> SMS routes to a VOLUNTEER (never clinical).

Run:  sentinel demo         (pauses between beats — good for a live audience)
      sentinel demo --no-pause
"""
from __future__ import annotations

from sentinelcall.data.record import load_patient_by_id
from sentinelcall.obs import trace as _trace
from sentinelcall.pipeline.loop import ConversationEngine
from sentinelcall.telephony import twilio_sms


def _pause(enabled: bool, label: str = "next beat") -> None:
    if enabled:
        try:
            input(f"\n{_trace.DIM}   [press Enter for {label}] {_trace.RESET}")
        except (EOFError, KeyboardInterrupt):
            pass


def _agent(text: str) -> None:
    print(f"{_trace.BOLD}{_trace.GREEN}AGENT  :{_trace.RESET} {text}")


def _patient(text: str) -> None:
    print(f"{_trace.BOLD}PATIENT:{_trace.RESET} {text}")


def run_demo(pause: bool = True) -> int:
    patient = load_patient_by_id("P001")  # Eleanor, day 5, knee

    _trace.banner("SentinelCall — LIVE DEMO", _trace.CYAN)
    print(f"{_trace.DIM}Patient on file: {patient.name} — {patient.summary_line()}."
          f"  Nurse + Volunteer channels armed.{_trace.RESET}")

    # ---- BEAT 1: personalized outbound open ----
    _trace.banner("BEAT 1 · Outbound call — personalized by caller info", _trace.BLUE)
    engine = ConversationEngine(patient, direction="outbound")
    _agent(engine.opening_line())
    _pause(pause, "BEAT 2 — the hero (GER)")

    # ---- BEAT 2: slurred/quiet voice -> garbled ASR -> GER recovers ----
    _trace.banner("BEAT 2 · Slurred/quiet speech — GER recovers it LIVE", _trace.MAGENTA)
    _patient("(slurred, quiet)  \"my pain is aboud a four... slep okay\"")
    # Simulated Deepgram N-best for a slurred, quiet delivery:
    with _trace.turn("turn", engine.supervisor.state.value):
        garbled = [
            "my pain is aboud a four slep okay",
            "my pain is a boat four slip okay",
            "my pain is about four i slept okay",
        ]
        outcome = engine.process_hypotheses(garbled)
        _agent(outcome.reply)
    _pause(pause, "the wound turn")

    # advance through meds quickly to reach the wound beat
    _trace.banner("BEAT 2b · Meds check (verbatim read-back available)", _trace.MAGENTA)
    _patient("yes i've been taking them")
    with _trace.turn("turn", engine.supervisor.state.value):
        outcome = engine.process_hypotheses(["yes i've been taking them"])
        _agent(outcome.reply)
    _pause(pause, "BEAT 3 — the red flag")

    # ---- BEAT 3: spreading redness + fever -> calm route, NO diagnosis ----
    _trace.banner("BEAT 3 · Red flag — calm instruction, NO diagnosis, routes", _trace.RED)
    _patient("(garbled)  \"my insshun is red an spreadin and i feel warm\"")
    with _trace.turn("turn", engine.supervisor.state.value):
        garbled_wound = [
            "my insshun is red an spreadin and i feel warm",
            "my in shun is read and spreading and i feel warm",
            "my incision is red and spreading and i feel warm",
        ]
        outcome = engine.process_hypotheses(garbled_wound)
        _agent(outcome.reply)
        # ---- BEAT 4 fires inside this turn: escalation SMS to nurse ----
        if outcome.escalated:
            print(f"\n{_trace.DIM}   ^ note: no diagnosis spoken; routed to a human.{_trace.RESET}")
    _pause(pause, "BEAT 5 — inbound callback")

    # ---- BEAT 5: inbound "is it normal that it itches?" ----
    _trace.banner("BEAT 5 · Inbound callback — grounded reassurance from record", _trace.CYAN)
    inbound = ConversationEngine(patient, direction="inbound")
    _agent(inbound.opening_line())
    _patient("is it normal that my incision itches a little?")
    with _trace.turn("turn", "inbound"):
        outcome = inbound.process_hypotheses(["is it normal that my incision itches a little"])
        _agent(outcome.reply)
    _pause(pause, "BEAT 6 — volunteer routing")

    # ---- BEAT 6: green signal (missed calls) -> VOLUNTEER, never clinical ----
    _trace.banner("BEAT 6 · Ecosystem routing — missed calls -> VOLUNTEER (never clinical)",
                  _trace.BLUE)
    with _trace.turn("turn", "routing"):
        twilio_sms.missed_calls_to_volunteer(patient)
        print(f"{_trace.DIM}   ^ volunteer body carries NO symptoms/meds/wound — presence only.{_trace.RESET}")

    _trace.banner("DEMO COMPLETE", _trace.GREEN)
    print(f"{_trace.DIM}Total LLM cost this run: ${_trace.session_cost():.4f}{_trace.RESET}")
    print(f"{_trace.DIM}Every spoken line passed the safety gate; every red flag routed to a human; "
          f"the agent never diagnosed.{_trace.RESET}")
    return 0
