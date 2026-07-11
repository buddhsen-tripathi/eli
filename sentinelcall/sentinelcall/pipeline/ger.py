"""GER — Generative Error Correction. THE HERO.

Standard voice agents fail elderly patients at the ASR layer, silently: the
transcript is simply wrong and nothing flags it. Even strong ASR hits ~52% word
error rate on dysarthric speech. A naive Deepgram-and-go pipeline mis-hears one
in four to one in two utterances from exactly the patients who get readmitted.

GER is the two-stage pattern that won the INTERSPEECH 2025 Speech Accessibility
Challenge: instead of trusting ONE transcript, take the ASR N-best hypotheses
and let the LLM pick/repair the most clinically-plausible transcription using
narrow post-op domain context.

    ["my insshun is red an wet"] -> "my incision is red and weeping"

Confidence rule (graceful degradation floor): if confidence stays LOW and the
turn touches a safety-critical field, DO NOT guess -> emit a read-back
confirmation instead ("I heard your incision is red — did I get that right?").
Negative-confirmation discipline: uncertainty never clears a red flag.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from sentinelcall.config import get_settings
from sentinelcall.gateway.llm import Message, llm
from sentinelcall.obs import trace as _trace


# Safety-critical topics: if the repaired transcript touches any of these AND
# confidence is low, we must read back rather than accept silently.
_SAFETY_CRITICAL_TERMS = [
    "incision", "wound", "redness", "red", "pus", "drainage", "bleeding",
    "fever", "temperature", "chills", "pain", "swelling", "swollen", "calf",
    "leg", "clot", "fell", "fall", "dizzy", "breath", "chest", "medication",
    "pill", "dose", "milligram", "blood thinner", "infection", "confused",
]

# Narrow domain lexicon the model is told to prefer — anchors the correction so
# "insshun" resolves to "incision", not "insertion".
_DOMAIN_LEXICON = (
    "incision, wound, dressing, gauze, staples, sutures, swelling, redness, "
    "warmth, drainage, weeping, discharge, pus, bruising, fever, chills, "
    "acetaminophen, oxycodone, aspirin, enoxaparin, blood thinner, walker, "
    "cane, physical therapy, follow-up, calf, deep vein thrombosis, clot"
)


@dataclass
class GERResult:
    repaired: str
    confidence: float          # 0..1, model's clinical-plausibility confidence
    hypotheses: List[str]      # raw ASR N-best (for the trace panel)
    changed: bool              # did GER change the top hypothesis?
    safety_critical: bool      # touches a safety-critical field?
    needs_readback: bool       # low confidence + safety-critical => confirm
    readback_prompt: Optional[str] = None  # the "did I get that right?" line
    raw: Dict[str, Any] = field(default_factory=dict)


_SYSTEM = (
    "You are the speech-recovery stage of a post-operative recovery phone agent "
    "for elderly patients. Elderly, post-op, dysarthric, quiet, or accented "
    "speech is frequently mis-transcribed. You are given several raw ASR "
    "hypotheses for ONE short utterance. Your job is to recover the single most "
    "clinically-plausible transcription of what the patient actually said.\n\n"
    "Rules:\n"
    "1. Prefer interpretations grounded in the post-op recovery domain. Common "
    "terms include: " + _DOMAIN_LEXICON + ".\n"
    "2. Repair obvious phonetic errors (e.g. 'insshun'->'incision', "
    "'wet/wep'->'weeping', 'fee ver'->'fever').\n"
    "3. Do NOT invent symptoms not supported by any hypothesis. If the "
    "hypotheses genuinely disagree on a clinical fact, keep it and lower your "
    "confidence.\n"
    "4. Output ONLY strict JSON, no prose."
)


def _build_user_prompt(hypotheses: List[str], context: Dict[str, Any]) -> str:
    surgery = context.get("surgery", "recent surgery")
    day = context.get("post_op_day", "unknown")
    state = context.get("state", "")
    recent = context.get("recent_fields", {})
    lines = [
        f"Patient context: {surgery}, post-op day {day}."
        + (f" Current question topic: {state}." if state else ""),
    ]
    if recent:
        lines.append(f"Recently reported: {recent}.")
    lines.append("")
    lines.append("Raw ASR hypotheses (best first):")
    for i, h in enumerate(hypotheses, 1):
        lines.append(f'  {i}. "{h}"')
    lines.append("")
    lines.append(
        "Return JSON: {\"repaired\": <string>, \"confidence\": <0..1 float>, "
        "\"reasoning\": <short string>}. `confidence` is how sure you are that "
        "`repaired` is what the patient said, given the domain."
    )
    return "\n".join(lines)


def _touches_safety_critical(text: str) -> bool:
    low = text.lower()
    return any(term in low for term in _SAFETY_CRITICAL_TERMS)


def _tokens(text: str) -> List[str]:
    import re
    return re.findall(r"[a-z]+", text.lower())


def _phonetic_key(word: str) -> str:
    """Very cheap phonetic reduction so 'insshun' and 'incision' collapse to the
    same skeleton but 'cases' does not. Steps: lowercase; map c/s/z->s, k->s
    before nothing (keep simple), ph->f; drop vowels except a leading one;
    collapse runs of the same consonant. Good enough to anchor GER repairs."""
    w = word.lower()
    w = w.replace("ph", "f").replace("sh", "s").replace("ci", "si").replace("ti", "si")
    w = w.replace("c", "s").replace("z", "s").replace("k", "s")
    out = []
    for i, ch in enumerate(w):
        if ch in "aeiou":
            if i == 0:
                out.append(ch)
            continue
        if out and out[-1] == ch:
            continue
        out.append(ch)
    return "".join(out)


def _phonetically_near(term: str, hyp_tokens: List[str]) -> bool:
    """Is `term` plausibly a repair of some token the ASR actually produced?
    True if a hypothesis token shares a 4-char prefix, is within a small edit
    distance, OR reduces to a near-identical phonetic key. This anchors
    'insshun'->'incision' (same phonetic key) while blocking 'cases'->'incision'
    (different key, far edit distance)."""
    term_key = _phonetic_key(term)
    for tok in hyp_tokens:
        if tok == term:
            return True
        if min(len(tok), len(term)) >= 4 and tok[:4] == term[:4]:
            return True
        if _edit_distance(tok, term) <= max(1, min(len(tok), len(term)) // 3):
            return True
        # phonetic-skeleton match (the real anchor for garbled elderly speech)
        tk = _phonetic_key(tok)
        if tk and term_key and _edit_distance(tk, term_key) <= 1:
            return True
    return False


def _edit_distance(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[-1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _reject_hallucinated_terms(repaired: str, hypotheses: List[str]) -> List[str]:
    """Return the list of SAFETY-CRITICAL clinical terms the repair INTRODUCED
    that aren't supported (present or phonetically near a token) by ANY raw
    hypothesis. A non-empty list means GER invented a symptom -> reject the
    repair. This is the guard against the 'cases'->'incision' hallucination."""
    all_hyp_tokens: List[str] = []
    for h in hypotheses:
        all_hyp_tokens.extend(_tokens(h))
    hyp_set = set(all_hyp_tokens)
    invented = []
    for term in _SAFETY_CRITICAL_TERMS:
        if term not in repaired.lower():
            continue
        if term in hyp_set:
            continue  # patient actually said it (in some hypothesis)
        if _phonetically_near(term, all_hyp_tokens):
            continue  # plausible phonetic repair of something they said
        invented.append(term)  # appears ONLY in the repair, from nowhere
    return invented


def _make_readback(repaired: str) -> str:
    """Turn a repaired statement into a gentle read-back confirmation."""
    r = repaired.strip().rstrip(".")
    # Strip a leading "my/i" to phrase it back naturally.
    return f"I want to make sure I heard you right. I heard: {r}. Did I get that right?"


def correct(
    hypotheses: List[str],
    context: Optional[Dict[str, Any]] = None,
    *,
    confirm_threshold: Optional[float] = None,
    trace_panel: bool = True,
) -> GERResult:
    """Run GER over ASR N-best hypotheses.

    hypotheses: Deepgram alternatives, best-first. Empty list -> empty result.
    context: {surgery, post_op_day, state, recent_fields}.
    """
    settings = get_settings()
    thresh = settings.ger_confirm_threshold if confirm_threshold is None else confirm_threshold
    context = context or {}
    hyps = [h for h in hypotheses if h and h.strip()]

    if not hyps:
        return GERResult(repaired="", confidence=0.0, hypotheses=[], changed=False,
                         safety_critical=False, needs_readback=False)

    top = hyps[0].strip()

    # Single confident hypothesis with no alternatives: still run repair only if
    # it looks garbled would be nice, but for the demo we always consult the LLM
    # when there's >1 hypothesis; with exactly 1 we still repair (elderly speech
    # is the whole point). Kept as one path for determinism.
    try:
        messages = [
            Message(role="system", content=_SYSTEM),
            Message(role="user", content=_build_user_prompt(hyps, context)),
        ]
        obj = llm().complete_json(messages, model=settings.ger_model, max_tokens=300)
    except Exception as exc:  # LLM/key failure -> fail safe to top hypothesis, low conf
        _trace.event("ger.error", error=repr(exc))
        obj = {}

    repaired = (obj.get("repaired") or top).strip()
    try:
        confidence = float(obj.get("confidence", 0.0))
    except Exception:
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))
    # If the LLM failed entirely, don't claim confidence in the raw hypothesis.
    if not obj:
        confidence = min(confidence, 0.4)

    # HALLUCINATION GUARD: GER may pick/repair from the N-best, but it must NOT
    # invent safety-critical symptoms that aren't in any hypothesis. If it added
    # a clinical term from nowhere (e.g. "cases"->"incision"), reject the repair,
    # revert to the raw top hypothesis, and drop confidence so nothing downstream
    # treats the invented symptom as real. Uncertainty never manufactures a flag.
    invented = _reject_hallucinated_terms(repaired, hyps)
    if invented:
        _trace.line("GER", f"REJECTED hallucinated term(s) {invented} -> revert to raw",
                    _trace.RED)
        repaired = top
        confidence = min(confidence, 0.4)

    changed = repaired.lower() != top.lower()
    safety_critical = _touches_safety_critical(repaired) or _touches_safety_critical(top)
    needs_readback = safety_critical and confidence < thresh
    readback = _make_readback(repaired) if needs_readback else None

    action = "READ-BACK (low conf, safety-critical)" if needs_readback else (
        "accept" if confidence >= thresh else "accept (low conf, non-critical)"
    )

    result = GERResult(
        repaired=repaired,
        confidence=confidence,
        hypotheses=hyps,
        changed=changed,
        safety_critical=safety_critical,
        needs_readback=needs_readback,
        readback_prompt=readback,
        raw=obj,
    )

    if trace_panel:
        _trace.show_ger(hyps, repaired, confidence, changed=changed, action=action)

    return result
