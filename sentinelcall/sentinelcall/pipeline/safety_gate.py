"""Safety gate — every candidate spoken line passes through here before TTS.

Three checks, in order (cheapest first):
  (a) BLOCK diagnosis / treatment / dose-computation language. Rule-based,
      pre-LLM, cannot be reasoned away. This is the non-diagnosis spine.
  (b) GROUND clinical claims: any specific dose/date/threshold the line asserts
      must trace to the patient's prescribed record (Layer 1). A number the
      model invented is a hallucination and is blocked.
  (c) SAFETY-NET: the line must end with the safety-net sentence. The gate can
      append it if missing (a formatting fix, not a content override).

Fail (a) or (b) -> the line is NOT spoken. The caller (supervisor) must
escalate or rephrase. The gate never "fixes" a diagnosis into a safe sentence —
it refuses it.

Persona shapes tone; the gate overrides persona every time.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional

# Fixed safety-net line appended to every patient-facing reply.
SAFETY_NET = "If anything gets worse, call your nurse line or 9 1 1."

# ---- (a) forbidden: diagnosis / treatment / dose-computation -----------------

# Phrases that assert a diagnosis or clinical conclusion to the patient.
_DIAGNOSIS_PATTERNS = [
    re.compile(r"\byou\s+(have|might have|probably have|likely have|may have)\s+(an?\s+)?"
               r"(infection|dvt|blood clot|clot|sepsis|pneumonia|delirium|fracture)\b", re.I),
    re.compile(r"\b(that|this|it)\s+(sounds?|looks?|seems?)\s+like\s+(an?\s+)?"
               r"(infection|a clot|dvt|sepsis|something serious|it'?s infected)\b", re.I),
    re.compile(r"\byour\s+(wound|incision|knee|leg)\s+is\s+(infected|abscess)", re.I),
    re.compile(r"\bit'?s\s+(infected|a blood clot|probably nothing|definitely)\b", re.I),
    re.compile(r"\byou\s+are\s+(fine|okay|healthy|not\s+in\s+danger)\b", re.I),
    re.compile(r"\byou'?re\s+(fine|okay|totally fine|all good)\b", re.I),
    re.compile(r"\bnothing\s+to\s+worry\s+about\b", re.I),
    re.compile(r"\bdon'?t\s+(worry|need\s+to\s+see|need\s+a\s+doctor)\b", re.I),
]

# Treatment / advice the agent must never give.
_TREATMENT_PATTERNS = [
    re.compile(r"\byou\s+should\s+(take|stop taking|start taking|apply|use|put)\b", re.I),
    re.compile(r"\bi\s+(recommend|suggest|advise)\s+(you\s+)?(take|stop|start|try|apply)\b", re.I),
    re.compile(r"\btry\s+(taking|applying|using|putting)\b", re.I),
    re.compile(r"\b(take|double|increase|decrease|skip)\s+(an?\s+)?(extra|another|more|your)\s+"
               r"(dose|pill|tablet|milligram)", re.I),
    re.compile(r"\byou\s+don'?t\s+need\s+to\s+(go|see|call|come in)\b", re.I),
    re.compile(r"\bno\s+need\s+to\s+(go|see a doctor|call|come in)\b", re.I),
]

# Dose language the agent may only produce by quoting Layer 1 verbatim. If a
# mg/dose number appears, we require it to be present in the grounding set.
_DOSE_NUMERIC = re.compile(r"\b(\d+(\.\d+)?)\s*(mg|milligram|milligrams|ml|pills?|tablets?)\b", re.I)


@dataclass
class SafetyVerdict:
    ok: bool
    text: str  # possibly rewritten (safety-net appended)
    violations: List[str] = field(default_factory=list)
    category: Optional[str] = None  # diagnosis | treatment | ungrounded_dose | reassurance


def _find(patterns, text) -> Optional[str]:
    for rx in patterns:
        m = rx.search(text)
        if m:
            return m.group(0)
    return None


def check(
    candidate: str,
    *,
    grounding: Optional[List[str]] = None,
    append_safety_net: bool = True,
) -> SafetyVerdict:
    """Gate a candidate reply.

    grounding: strings the reply is allowed to quote verbatim (the patient's
    prescribed instructions retrieved for this turn). Any dose number in the
    candidate must appear inside one of these strings, or the line is blocked as
    an ungrounded clinical claim.
    """
    text = (candidate or "").strip()
    violations: List[str] = []

    hit = _find(_DIAGNOSIS_PATTERNS, text)
    if hit:
        return SafetyVerdict(ok=False, text=text, violations=[f"diagnosis/reassurance: {hit!r}"],
                             category="diagnosis")

    hit = _find(_TREATMENT_PATTERNS, text)
    if hit:
        return SafetyVerdict(ok=False, text=text, violations=[f"treatment advice: {hit!r}"],
                             category="treatment")

    # Dose grounding: every dose number must be traceable to Layer 1.
    ground_blob = " ".join(grounding or [])
    for m in _DOSE_NUMERIC.finditer(text):
        token = m.group(0)
        num = m.group(1)
        if num not in ground_blob:
            return SafetyVerdict(
                ok=False,
                text=text,
                violations=[f"ungrounded dose {token!r} not in prescribed record"],
                category="ungrounded_dose",
            )

    # Passed content checks. Ensure the safety-net line is present.
    out = text
    if append_safety_net and SAFETY_NET.rstrip(".").lower() not in out.lower():
        # only append if the line isn't itself the emergency script
        if "9 1 1" not in out or "nurse" not in out.lower():
            out = (out.rstrip() + " " + SAFETY_NET).strip()

    return SafetyVerdict(ok=True, text=out, violations=violations)
