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
        "Hello {name}, this is your recovery check-in call. You're on day "
        "{post_op_day} after your {surgery_short}. I'll go slowly. "
        "How are you feeling today?"
    ),
    State.CHECKIN: (
        "Thank you for telling me. On a scale of zero to ten, how would you "
        "rate your pain right now? And how have you been sleeping and eating?"
    ),
    State.MEDS: (
        "Let's go over your medicines. Have you been able to take them as "
        "prescribed? Tell me if anything has been confusing."
    ),
    State.WOUND: (
        "Now let's check your incision. Have you noticed any spreading redness, "
        "any fluid or drainage, or does the skin feel warm or more painful?"
    ),
    State.SCREEN: (
        "A couple of safety questions. Have you had any falls or near-falls "
        "since we last spoke? And are you feeling clear-headed today?"
    ),
    State.CLOSE: (
        "Thank you, {name}. I've noted everything for your care team. I'll "
        "check in with you again tomorrow. You can also call this number any "
        "time if you have a question."
    ),
}
