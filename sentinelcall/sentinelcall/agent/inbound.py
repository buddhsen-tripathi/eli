"""Inbound Q&A — the patient calls US (the 2am "is this normal?" call).

Inbound needs MORE guardrail, not less. Order per turn:
  1. Emergency screen FIRST (handled upstream in the pipeline loop, pre-LLM).
  2. Rule-based red-flag check on the question. A red flag -> route to nurse,
     never answer the clinical question directly.
  3. Otherwise: reassure-with-grounding — answer ONLY from the patient's own
     discharge record (Layer 1) and the general reference protocol (Layer 2),
     framed as "your discharge sheet says...". Never a yes/no to "should I go to
     the ER"; never a diagnosis; always keep the door open to seeking care.

Every line still passes the safety gate before it can be spoken.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from sentinelcall.agent import redflags as rf
from sentinelcall.data.record import Patient
from sentinelcall.data.reference_rag import reference_rag
from sentinelcall.gateway.llm import Message, llm
from sentinelcall.pipeline import safety_gate
from sentinelcall.obs import trace as _trace


_INBOUND_PERSONA = (
    "You are SentinelCall answering an INBOUND call from an elderly post-op "
    "patient who has a question. You are warm, slow, and reassuring in TONE, "
    "but you are NOT a medical advisor.\n\n"
    "ABSOLUTE RULES:\n"
    "- Answer ONLY using the patient's own discharge instructions and the "
    "general reference notes provided below. If the answer isn't in them, say "
    "you're not sure and a nurse can help — 'I don't know' is a safe answer.\n"
    "- NEVER diagnose or name a condition. NEVER say it is or isn't an "
    "infection/clot/etc.\n"
    "- NEVER recommend or compute a treatment or dose. You may quote the "
    "patient's prescribed instruction VERBATIM if directly relevant.\n"
    "- NEVER answer 'should I go to the ER / call the doctor?' with yes or no. "
    "Encourage them to contact their nurse line, and never discourage seeking "
    "care.\n"
    "- Ground your answer: say something like 'your discharge sheet notes "
    "that...'. Keep it to 1-2 short sentences."
)


@dataclass
class InboundTurn:
    reply: str
    escalate: bool = False
    escalation: Optional[rf.RedFlagResult] = None
    grounded_on: List[str] = field(default_factory=list)


def answer(patient: Patient, question: str) -> InboundTurn:
    """Answer one inbound question, grounded + gated. Emergency screen is assumed
    already run upstream."""
    # Red-flag first: if the question itself reports a red flag, route.
    flags = rf.detect(question)
    if flags.has_clinical:
        _trace.line("INBOUND", f"red-flag in question -> {flags.route.value}", _trace.RED)
        line = (
            "Thank you for calling and telling me. That's something I want a "
            "nurse to look at, so I'm going to have your care team reach out to "
            "you right away."
        )
        v = safety_gate.check(line)
        return InboundTurn(reply=v.text, escalate=True, escalation=flags)

    # Grounding: patient's own record + reference protocol (scoped to surgery).
    rag = reference_rag()
    chunks = rag.retrieve(question, patient.surgery, k=2)
    ref_notes = "\n".join(f"[{c.heading}] {c.text}" for c in chunks)
    prescribed = patient.prescribed
    discharge_block = (
        f"Wound care: {prescribed.get('wound_care','')}\n"
        f"Activity: {prescribed.get('activity','')}\n"
        f"Follow-up: {prescribed.get('follow_up',{})}\n"
        "Medications (quote verbatim if relevant):\n"
        + "\n".join(f'- {m["name"]}: "{m["verbatim_instruction"]}"'
                    for m in patient.medications)
    )

    grounding = [m.get("verbatim_instruction", "") for m in patient.medications]

    try:
        user = (
            f"Patient (day {patient.post_op_day} after {patient.surgery}) asks: "
            f'"{question}"\n\n'
            f"THEIR discharge instructions:\n{discharge_block}\n\n"
            f"General reference notes for this surgery:\n{ref_notes}\n\n"
            "Answer warmly in 1-2 short sentences, grounded in the above. If it "
            "isn't covered, say a nurse can help."
        )
        resp = llm().complete(
            [Message(role="system", content=_INBOUND_PERSONA),
             Message(role="user", content=user)],
            max_tokens=180,
        )
        candidate = (resp.text or "").strip().strip('"')
    except Exception as exc:
        _trace.event("inbound.compose_error", error=repr(exc))
        candidate = (
            "I'm not certain about that one. Let me have your nurse line help "
            "you with it."
        )

    v = safety_gate.check(candidate, grounding=grounding)
    if not v.ok:
        _trace.line("SAFETY-GATE", f"BLOCKED inbound ({v.category})", _trace.RED)
        safe = (
            "I don't want to guess on that. Your nurse line can give you the "
            "right answer, and please call them or 9 1 1 if anything gets worse."
        )
        v = safety_gate.check(safe)
    return InboundTurn(reply=v.text, grounded_on=[c.heading for c in chunks])
