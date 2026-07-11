"""Layer 1 (Prescribed, authoritative) + Layer 3 (Discussed, longitudinal).

Layer 1 — the patient's OWN prescribed record: meds, verbatim dose
instructions, wound care, follow-up, red-flag thresholds. Stored as structured
JSON. Quoted VERBATIM. NEVER RAG'd, never paraphrased by the model.

Layer 3 — what the patient reported, extracted per call into structured fields
(pain:int, wound_status:enum, meds_adherent:bool, notes:str). NOT raw-transcript
RAG. Appended to the record so trend logic can run on the clinician side.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from sentinelcall.config import DATA_DIR

_PATIENTS_FILE = DATA_DIR / "patients.json"
# Layer 3 log lives beside the patient file; appended, never overwritten.
_CALLS_FILE = DATA_DIR / "call_records.json"


def _normalize_phone(phone: str) -> str:
    """Strip everything but digits and a leading +, so +1 (555) 123-0001 and
    +15551230001 compare equal."""
    if not phone:
        return ""
    phone = phone.strip()
    keep = "".join(ch for ch in phone if ch.isdigit())
    return ("+" + keep) if phone.startswith("+") or len(keep) >= 10 else keep


@dataclass
class Patient:
    patient_id: str
    name: str
    preferred_name: str
    phone: str
    age: int
    surgery: str
    surgery_date: str
    post_op_day: int
    surgeon: str
    caregiver: Dict[str, Any]
    prescribed: Dict[str, Any]

    # ---- Layer 1 verbatim accessors (never paraphrased) ----

    @property
    def medications(self) -> List[Dict[str, Any]]:
        return self.prescribed.get("medications", [])

    @property
    def red_flag_thresholds(self) -> Dict[str, Any]:
        return self.prescribed.get("red_flag_thresholds", {})

    def med(self, name_query: str) -> Optional[Dict[str, Any]]:
        """Find a prescribed medication by (loose) name match."""
        q = name_query.lower().strip()
        for m in self.medications:
            if q in m.get("name", "").lower() or m.get("name", "").lower() in q:
                return m
        return None

    def summary_line(self) -> str:
        return f"{self.preferred_name}, day {self.post_op_day} after {self.surgery.lower()}"


def guest_patient(phone: str = "") -> Patient:
    """A synthetic, record-less caller for UNKNOWN inbound numbers (e.g. a judge
    calling the demo line). It carries NO clinical data — empty `prescribed`, so
    no medications, empty red-flag thresholds, and empty grounding. This lets an
    unknown caller flow through the IDENTICAL emergency-screen + safety-gate + Q&A
    pipeline without ever exposing another patient's record: grounding is empty,
    so the inbound Q&A can only answer from the general reference protocol or fall
    back to 'a nurse can help'. Generic `surgery` routes Layer-2 RAG to
    protocol_generic.md."""
    return Patient(
        patient_id="GUEST",
        name="Caller",
        preferred_name="there",  # -> "Hello there, this is SentinelCall"
        phone=_normalize_phone(phone),
        age=0,
        surgery="a recent procedure",
        surgery_date="",
        post_op_day=0,
        surgeon="",
        caregiver={},
        prescribed={},  # no meds, no thresholds -> nothing personal to leak
    )


def _load_raw() -> Dict[str, Any]:
    with open(_PATIENTS_FILE) as f:
        return json.load(f)


def all_patients() -> List[Patient]:
    return [Patient(**p) for p in _load_raw().get("patients", [])]


def load_patient_by_id(patient_id: str) -> Optional[Patient]:
    for p in all_patients():
        if p.patient_id == patient_id:
            return p
    return None


def load_patient_by_phone(phone: str) -> Optional[Patient]:
    target = _normalize_phone(phone)
    for p in all_patients():
        if _normalize_phone(p.phone) == target:
            return p
    return None


def verbatim_med_instruction(patient: Patient, med_name: str) -> Optional[str]:
    """Return the EXACT prescribed instruction string for a medication, or None.

    This is the only sanctioned way to speak a dose. The supervisor must call
    this and read the result back word-for-word; it must never let the model
    generate a dose from memory."""
    m = patient.med(med_name)
    if not m:
        return None
    return m.get("verbatim_instruction")


# ---------------------------------------------------------------------------
# Layer 3 — structured extraction per call
# ---------------------------------------------------------------------------


@dataclass
class CallExtract:
    """Structured fields extracted from one call. This is what gets stored and
    trended — NOT the raw transcript."""

    patient_id: str
    direction: str = "outbound"  # outbound | inbound
    post_op_day: Optional[int] = None
    pain: Optional[int] = None  # 0-10
    sleep: Optional[str] = None  # good | poor | none | unknown
    appetite: Optional[str] = None  # normal | reduced | none | unknown
    wound_status: Optional[str] = None  # normal | mild_concern | red_flag | unknown
    meds_adherent: Optional[bool] = None
    fever: Optional[bool] = None
    fall: Optional[bool] = None
    confusion_signal: Optional[bool] = None
    red_flags: List[str] = field(default_factory=list)
    escalated: bool = False
    escalation_channel: Optional[str] = None  # nurse | volunteer | 911 | none
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def append_call_record(extract: CallExtract, *, timestamp: Optional[str] = None) -> None:
    """Append a Layer-3 extract to the longitudinal call log. Timestamp is
    passed in (callers stamp it) so this module stays clock-free and testable."""
    records: List[Dict[str, Any]] = []
    if _CALLS_FILE.exists():
        try:
            with open(_CALLS_FILE) as f:
                records = json.load(f)
        except Exception:
            records = []
    entry = extract.to_dict()
    if timestamp:
        entry["ts"] = timestamp
    records.append(entry)
    with open(_CALLS_FILE, "w") as f:
        json.dump(records, f, indent=2)


def set_patient_phone(patient_id: str, phone: str) -> bool:
    """Point a seeded patient's phone at a real number (e.g. your own cell) so
    `sentinel call <id>` dials it and inbound recognizes it. Rewrites
    patients.json in place. Returns True on success."""
    raw = _load_raw()
    found = False
    for p in raw.get("patients", []):
        if p.get("patient_id") == patient_id:
            p["phone"] = phone.strip()
            found = True
            break
    if found:
        with open(_PATIENTS_FILE, "w") as f:
            json.dump(raw, f, indent=2)
    return found


def call_history(patient_id: str) -> List[Dict[str, Any]]:
    """Prior Layer-3 extracts for a patient, oldest first — feeds trend logic."""
    if not _CALLS_FILE.exists():
        return []
    try:
        with open(_CALLS_FILE) as f:
            records = json.load(f)
    except Exception:
        return []
    return [r for r in records if r.get("patient_id") == patient_id]
