"""Emergency screen — RUNS FIRST, on every turn, inbound and outbound.

RULE-BASED / PRE-LLM by design so it can't be reasoned away. This is the top of
the safety spine: before GER, before the supervisor, before anything, we scan
the caller's words for 911 situations. A hit short-circuits the whole pipeline
to "Hang up and call 911 now" + fires an alert.

Because ASR may garble the input, we match on tolerant patterns over BOTH the
raw hypotheses and the (later) repaired transcript — emergency screening sees
the raw text first so a bad transcription can never hide an emergency.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional


# Each rule: a human label + a compiled tolerant regex. Patterns are written to
# survive light mis-transcription (missing letters, run-together words) and to
# require the *dangerous* combination, not just a scary word in isolation.
_RULES: List[tuple] = [
    (
        "chest pain / pressure",
        re.compile(
            r"\b(chest\s*(pain|pressure|tight|tightness|hurt)"
            r"|pain\s+in\s+my\s+chest"
            r"|pressure\s+(on|in)\s+my\s+chest)\b",
            re.I,
        ),
    ),
    (
        "trouble breathing",
        re.compile(
            r"\b(can'?t\s*(breath|breathe)|cannot\s*breathe|trouble\s*breathing"
            r"|short(ness)?\s*of\s*breath|hard\s*to\s*breathe|struggling\s*to\s*breathe"
            r"|out\s*of\s*breath\s*and)\b",
            re.I,
        ),
    ),
    (
        "uncontrolled bleeding",
        re.compile(
            r"\b(bleeding\s*(a\s*lot|badly|heavily|everywhere|won'?t\s*stop|will\s*not\s*stop)"
            r"|can'?t\s*stop\s*the\s*bleeding|lot\s*of\s*blood|gushing|pouring\s*blood"
            r"|soaked\s*(through|the))\b",
            re.I,
        ),
    ),
    (
        "fall — can't get up / hit head",
        re.compile(
            r"\b((i\s*)?fell\s*(down|and|on)?.{0,20}(can'?t|cannot)\s*(get\s*up|move|stand)"
            r"|can'?t\s*get\s*up|hit\s*my\s*head|fell\s*and\s*hit"
            r"|on\s*the\s*floor\s*and\s*(can'?t|cannot))\b",
            re.I,
        ),
    ),
    (
        "possible stroke",
        re.compile(
            r"\b(face\s*(is\s*)?droop|can'?t\s*(feel|move)\s*(my\s*)?(arm|face|side)"
            r"|slurr(ed|ing)|sudden\s*weakness\s*on\s*one\s*side)\b",
            re.I,
        ),
    ),
    (
        "passing out / unresponsive",
        re.compile(
            r"\b(passing\s*out|about\s*to\s*pass\s*out|blacking\s*out"
            r"|unrespons|not\s*waking\s*up|won'?t\s*wake\s*up)\b",
            re.I,
        ),
    ),
]

# Spoken response is deliberately fixed, short, and slow-cadence friendly.
EMERGENCY_SCRIPT = (
    "This may be an emergency. Please hang up now and call 9 1 1 right away. "
    "If you can, unlock your door for help. I am also alerting your care team now."
)


@dataclass
class EmergencyResult:
    is_emergency: bool
    trigger: Optional[str] = None
    matched_text: Optional[str] = None


def screen(*texts: str) -> EmergencyResult:
    """Screen one or more candidate texts (raw hypotheses + repaired). Returns on
    the FIRST rule that fires. Empty/none inputs are safe (no emergency)."""
    for t in texts:
        if not t:
            continue
        for label, rx in _RULES:
            m = rx.search(t)
            if m:
                return EmergencyResult(is_emergency=True, trigger=label, matched_text=m.group(0))
    return EmergencyResult(is_emergency=False)


def screen_many(texts: List[str]) -> EmergencyResult:
    return screen(*[t for t in texts if t])
