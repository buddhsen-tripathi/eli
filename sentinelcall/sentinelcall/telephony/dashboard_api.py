"""Read-only JSON API for the nurse triage dashboard.

The dashboard is a clinician-facing command center over the SAME data the voice
agent produces: Layer-1 prescribed records (patients.json) and Layer-3 per-call
extracts (call_records.json). No new source of truth — this just SHAPES that data
for a triage worklist, patient detail, and trends.

Design principle (mirrors the safety spine): the SERVER computes the clinical
triage priority, so ranking is authoritative and identical everywhere. The
frontend never invents severity.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from sentinelcall.data.record import (
    Patient,
    all_patients,
    call_history,
    load_patient_by_id,
)


# ---- triage scoring (authoritative, server-side) ---------------------------
#
# Priority tiers map to the dashboard's severity semantics:
#   "critical" -> a clinical red flag / escalation on the latest call (act now)
#   "watch"    -> a soft concern trending the wrong way (pain high, meds missed)
#   "stable"   -> latest check-in clean
#   "nocontact"-> no successful check-in yet / overdue (operational, not clinical)

_TIER_RANK = {"critical": 0, "watch": 1, "nocontact": 2, "stable": 3}


def _latest_extract(patient_id: str) -> Optional[Dict[str, Any]]:
    hist = call_history(patient_id)
    return hist[-1] if hist else None


def _tier_for(patient: Patient, latest: Optional[Dict[str, Any]]) -> str:
    if latest is None:
        return "nocontact"
    if latest.get("escalated") or (latest.get("escalation_channel") in ("nurse", "911")):
        return "critical"
    if latest.get("red_flags"):
        return "critical"
    # soft-watch signals
    pain = latest.get("pain")
    watch = (
        (isinstance(pain, int) and pain >= 6)
        or latest.get("fever")
        or latest.get("fall")
        or latest.get("confusion_signal")
        or latest.get("meds_adherent") is False
        or latest.get("wound_status") in ("mild_concern", "red_flag")
    )
    return "watch" if watch else "stable"


def _reasons(latest: Optional[Dict[str, Any]]) -> List[str]:
    """Short, human, scannable chips explaining WHY a patient is flagged."""
    if not latest:
        return ["No check-in yet"]
    out: List[str] = []
    for rf in latest.get("red_flags", []) or []:
        out.append(str(rf).replace("_", " "))
    pain = latest.get("pain")
    if isinstance(pain, int) and pain >= 6:
        out.append(f"Pain {pain}/10")
    if latest.get("fever"):
        out.append("Fever")
    if latest.get("fall"):
        out.append("Fall")
    if latest.get("confusion_signal"):
        out.append("Confusion")
    if latest.get("meds_adherent") is False:
        out.append("Meds missed")
    ws = latest.get("wound_status")
    if ws in ("mild_concern", "red_flag"):
        out.append("Wound " + ws.replace("_", " "))
    return out or ["Check-in clear"]


def _patient_summary(patient: Patient) -> Dict[str, Any]:
    latest = _latest_extract(patient.patient_id)
    tier = _tier_for(patient, latest)
    hist = call_history(patient.patient_id)
    return {
        "patient_id": patient.patient_id,
        "name": patient.name,
        "preferred_name": patient.preferred_name,
        "age": patient.age,
        "surgery": patient.surgery,
        "post_op_day": patient.post_op_day,
        "surgeon": patient.surgeon,
        "phone": patient.phone,
        "tier": tier,
        "tier_rank": _TIER_RANK[tier],
        "reasons": _reasons(latest),
        "latest": latest,
        "pain_trend": [h.get("pain") for h in hist],
        "calls_count": len(hist),
        "escalation_channel": (latest or {}).get("escalation_channel"),
    }


def triage_list() -> List[Dict[str, Any]]:
    """All patients, ranked most-urgent first (critical -> watch -> nocontact ->
    stable), then by post-op day descending within a tier."""
    rows = [_patient_summary(p) for p in all_patients()]
    rows.sort(key=lambda r: (r["tier_rank"], -(r["post_op_day"] or 0)))
    return rows


def patient_detail(patient_id: str) -> Optional[Dict[str, Any]]:
    p = load_patient_by_id(patient_id)
    if not p:
        return None
    summary = _patient_summary(p)
    summary["history"] = call_history(patient_id)
    summary["prescribed"] = p.prescribed
    summary["caregiver"] = p.caregiver
    return summary


def dashboard_stats(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    counts = {"critical": 0, "watch": 0, "stable": 0, "nocontact": 0}
    for r in rows:
        counts[r["tier"]] = counts.get(r["tier"], 0) + 1
    return {
        "total": len(rows),
        "counts": counts,
        "needs_review": counts["critical"] + counts["watch"],
    }
