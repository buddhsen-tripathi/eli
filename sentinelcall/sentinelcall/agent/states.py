"""Conversation states S0..S7.

The state machine is the skeleton; the emergency screen, GER, and safety gate
wrap EVERY state (they are not states themselves). Each state has a fixed
purpose and a fixed set of structured fields it is trying to fill. Red-flag
detection can fire from any state and jump straight to ESCALATE.
"""
from __future__ import annotations

from enum import Enum


class State(str, Enum):
    IDENTIFY = "S0_IDENTIFY"   # match caller -> load record + post-op day
    GREET = "S1_GREET"         # warm, slow, personalized open
    CHECKIN = "S2_CHECKIN"     # pain, sleep, appetite
    MEDS = "S3_MEDS"           # adherence; catch confusion/double-dosing; verbatim read-back
    WOUND = "S4_WOUND"         # infection probes
    SCREEN = "S5_SCREEN"       # falls + passive delirium listen
    ESCALATE = "S6_ESCALATE"   # calm instruction (no dx) + SMS to nurse
    CLOSE = "S7_CLOSE"         # summarize, safety-net, next call, append fields

    INBOUND_GREET = "S1_INBOUND_GREET"  # known patient called US -> personalized open

    # Inbound-only pseudo-state: open-ended Q&A grounded in the record.
    INBOUND_QA = "S_INBOUND_QA"


# Linear happy-path order for the outbound check-in. Red flags divert to
# ESCALATE, then continue to CLOSE.
OUTBOUND_ORDER = [
    State.IDENTIFY,
    State.GREET,
    State.CHECKIN,
    State.MEDS,
    State.WOUND,
    State.SCREEN,
    State.CLOSE,
]


def next_state(current: State) -> State:
    """Advance along the outbound happy path. ESCALATE always returns to CLOSE."""
    if current == State.ESCALATE:
        return State.CLOSE
    try:
        i = OUTBOUND_ORDER.index(current)
    except ValueError:
        return State.CLOSE
    if i + 1 < len(OUTBOUND_ORDER):
        return OUTBOUND_ORDER[i + 1]
    return State.CLOSE


# The single structured probe each state asks. Kept short + slow-cadence
# friendly. These are TEMPLATES the supervisor personalizes; they are also the
# safe fallback if the LLM is unavailable.
STATE_PROMPTS = {
    State.GREET: (
        "Hi {name}, it's SentinelCall — your recovery check-in. It's day "
        "{post_op_day} since your {surgery_short}, and I just want to see how "
        "you're doing. No rush at all. How are you feeling today?"
    ),
    State.INBOUND_GREET: (
        "Hi {name}, it's SentinelCall. I've got your chart right here — you're "
        "on day {post_op_day} after your {surgery_short}. Since you've got me on "
        "the line, let's do your quick check-in. How have you been feeling?"
    ),
    State.CHECKIN: (
        "Just one thing at a time — right now, what's your pain like on a scale "
        "of zero to ten?"
    ),
    State.MEDS: (
        "How about your medicines — have they been easy to keep up with?"
    ),
    State.WOUND: (
        "Let's take a quick look at your incision. Have you noticed any redness "
        "spreading, or any fluid or warmth around it?"
    ),
    State.SCREEN: (
        "Almost done. Since we last talked, have you had any falls or close "
        "calls with your balance?"
    ),
    State.CLOSE: (
        "That's everything I needed, {name} — thank you. I've passed your notes "
        "to your care team, and I'll check in again soon. And remember, if "
        "anything gets worse, call your nurse line or 9 1 1 any time."
    ),
}
