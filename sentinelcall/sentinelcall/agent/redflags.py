"""Red-flag detection + routing (clinician-authored thresholds).

Distinct from the emergency screen: emergencies are 911-now situations that
short-circuit the call. Red flags are clinical concerns that warrant a NURSE
(not the agent diagnosing) — infection, blood clot, uncontrolled pain, med
confusion, falls, delirium.

Detection is rule-based + threshold-based over the structured fields the
supervisor extracts, cross-checked against the patient's OWN thresholds
(Layer 1). This keeps the trigger deterministic and auditable — a clinician can
read exactly why a flag fired. The LLM never gets to talk a red flag away
(negative-confirmation rule: safety-critical uncertainty escalates).

Routing follows the ecosystem table: clinical -> nurse; presence-only ->
volunteer. Clinical content NEVER goes down the volunteer channel.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class Route(str, Enum):
    NONE = "none"
    NURSE = "nurse"          # clinical
    VOLUNTEER = "volunteer"  # presence-only, NEVER clinical content
    EMERGENCY = "911"


@dataclass
class RedFlag:
    label: str
    detail: str
    route: Route
    clinical: bool  # True => nurse-only content; must never reach volunteer


# Keyword patterns over the (GER-repaired) transcript. Tuned for the post-op
# domain; conservative — err toward flagging (negative-confirmation discipline).
_INFECTION = re.compile(
    r"\b(spreading\s+red"
    # "redness ... is spreading/growing/bigger" with up to a few words between
    r"|red(ness)?\b(\s+\w+){0,4}\s+(is\s+)?(spreading|growing|getting\s+bigger|bigger|worse)"
    r"|(spreading|growing)\b(\s+\w+){0,3}\s+red"
    r"|pus|puss|oozing|weeping|foul|smell(s|y|ing)?|drainage|discharge"
    r"|wound\s+(is\s+)?open|opening\s+up|coming\s+apart|hot\s+to\s+the\s+touch"
    r"|(getting|feels?|feeling|more)\s+warm(er)?"
    r"|warm(er)?\s+(to\s+the\s+touch|around|near|and)"
    r"|more\s+red)\b",
    re.I,
)
_FEVER = re.compile(
    r"\b(fever|feverish|temperature\s+(is|of|was)|chills|shivering|hot\s+and\s+cold"
    r"|(101|102|103|104|100\.4|100\s+point\s+four|a\s+hundred\s+and))\b",
    re.I,
)
_CLOT = re.compile(
    r"\b(calf\s+\w*\s*(pain|swelling|swollen|tender|hurt)"
    r"|calf\s+is\s+\w*\s*(swollen|painful|tender|sore)"
    r"|(one|my)\s+(leg|calf)\s+is\s+\w*\s*swollen"
    r"|leg\s+(is\s+)?(really\s+)?swollen"
    r"|swelling\s+in\s+(one|my)\s+(leg|calf)"
    r"|charley\s+horse\s+that\s+won)\b",
    re.I,
)
_MED_CONFUSION = re.compile(
    r"\b(took\s+(two|both|double|extra)|double\s+dos|twice\s+as\s+much"
    r"|not\s+sure\s+(if|how\s+much|which)\s+(i\s+)?(took|should)"
    r"|mixed?\s+up\s+my\s+(pills|meds)|forgot\s+(to\s+take|my\s+shot|the\s+blood)"
    r"|skipped\s+my\s+(blood\s+thinner|shot|dose)|ran\s+out\s+of)\b",
    re.I,
)
_FALL = re.compile(
    r"\b(i\s+fell|had\s+a\s+fall|took\s+a\s+(fall|tumble)|slipped\s+and\s+fell"
    r"|almost\s+fell|nearly\s+fell|near\s*-?\s*fall|lost\s+my\s+balance)\b",
    re.I,
)
_CONFUSION = re.compile(
    r"\b(confused|can'?t\s+remember\s+(if|whether|what\s+day)"
    r"|(don'?t|do\s+not)\s+know\s+what\s+day"      # "don't know what day it is"
    r"|what\s+day\s+is\s+it"
    r"|(don'?t|do\s+not)\s+know\s+where\s+i\s+am"
    r"|feel\s+(foggy|muddled|mixed\s+up)|foggy|muddled)\b",
    re.I,
)

# Presence-only (non-clinical) signals -> volunteer channel.
_NO_FOOD = re.compile(
    r"\b(no\s+(food|groceries)|nothing\s+to\s+eat|haven'?t\s+eaten|out\s+of\s+food"
    r"|can'?t\s+get\s+(to\s+the\s+store|groceries))\b",
    re.I,
)
_ISOLATION = re.compile(
    r"\b(so\s+lonely|all\s+alone|no\s+one\s+(comes|visits|checks)|feel\s+isolated"
    r"|haven'?t\s+seen\s+anyone|nobody\s+to\s+talk)\b",
    re.I,
)


@dataclass
class RedFlagResult:
    flags: List[RedFlag] = field(default_factory=list)

    @property
    def has_clinical(self) -> bool:
        return any(f.clinical for f in self.flags)

    @property
    def route(self) -> Route:
        # Clinical wins over presence; emergency handled upstream.
        if any(f.route == Route.NURSE for f in self.flags):
            return Route.NURSE
        if any(f.route == Route.VOLUNTEER for f in self.flags):
            return Route.VOLUNTEER
        return Route.NONE

    @property
    def labels(self) -> List[str]:
        return [f.label for f in self.flags]


def detect(
    transcript: str,
    *,
    pain: Optional[int] = None,
    pain_threshold: int = 8,
) -> RedFlagResult:
    """Detect red flags over a repaired transcript plus known numeric fields.

    pain: if the supervisor extracted a pain score, we compare it against the
    patient's uncontrolled-pain threshold (Layer 1) here rather than trusting
    the model to decide it's a red flag.
    """
    t = transcript or ""
    flags: List[RedFlag] = []

    if _INFECTION.search(t):
        flags.append(RedFlag("infection", "Possible wound-infection signal in patient's report.",
                             Route.NURSE, clinical=True))
    if _FEVER.search(t):
        flags.append(RedFlag("fever", "Patient reported fever / chills.", Route.NURSE, clinical=True))
    if _CLOT.search(t):
        flags.append(RedFlag("possible_clot", "Calf pain/swelling — possible DVT, clinical review.",
                             Route.NURSE, clinical=True))
    if _MED_CONFUSION.search(t):
        flags.append(RedFlag("med_confusion", "Possible medication confusion / adherence issue.",
                             Route.NURSE, clinical=True))
    if _FALL.search(t):
        flags.append(RedFlag("fall", "Patient reported a fall or near-fall.", Route.NURSE, clinical=True))
    if _CONFUSION.search(t):
        # "confused about which pills/instructions" is medication confusion, not
        # delirium — don't raise the delirium flag for it (it's already caught as
        # med_confusion above). But bare "confused" or any disorientation cue
        # (foggy/muddled/what day is it/where am I) still fires delirium: we do
        # NOT weaken real delirium detection.
        med_scoped = re.search(
            r"confused\s+(about|on|by|with|over)\s+.{0,30}"
            r"(pill|medicine|medication|dose|instruction|paper|sheet|schedule)", t, re.I)
        disorientation = re.search(
            r"foggy|muddled|mixed\s+up|what\s+day|where\s+i\s+am|can'?t\s+remember", t, re.I)
        if not (med_scoped and not disorientation):
            flags.append(RedFlag("confusion", "Possible confusion/delirium signal — nurse assessment.",
                                 Route.NURSE, clinical=True))

    if pain is not None and pain >= pain_threshold:
        flags.append(RedFlag("uncontrolled_pain",
                             f"Pain {pain}/10 at or above threshold {pain_threshold}.",
                             Route.NURSE, clinical=True))

    # Presence-only signals (only meaningful if no clinical flag dominates, but
    # we still record them; routing picks nurse over volunteer automatically).
    if _NO_FOOD.search(t):
        flags.append(RedFlag("no_food", "Patient reports no food / cannot get groceries.",
                             Route.VOLUNTEER, clinical=False))
    if _ISOLATION.search(t):
        flags.append(RedFlag("isolation", "Patient reports loneliness / isolation.",
                             Route.VOLUNTEER, clinical=False))

    return RedFlagResult(flags=flags)
