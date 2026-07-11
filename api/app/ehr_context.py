"""
Build the dynamic-variable bundle the ElevenLabs agent gets on every call.

These map the patient's EHR (name, procedure, recovery day, meds, notes) plus the
current local time into the `{{...}}` placeholders the agent prompt references.
Same-timezone assumption: the clinic/patient local time comes from the TIMEZONE env
(defaults to US Pacific, matching the demo number). All values are strings — that's
what ElevenLabs dynamic_variables require.
"""

import os
from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import AsyncSessionLocal
from app.db_models import Medication, Patient

DEFAULT_TIMEZONE = os.environ.get("TIMEZONE", "America/Los_Angeles")


def _local_now() -> datetime:
    try:
        return datetime.now(ZoneInfo(DEFAULT_TIMEZONE))
    except Exception:
        return datetime.now()


def _recovery_day(surgery_date: date | None) -> str:
    if not surgery_date:
        return ""
    days = (_local_now().date() - surgery_date).days
    return str(days) if days >= 0 else ""


def _format_medications(meds: list[Medication]) -> str:
    active = [m for m in meds if m.active]
    if not active:
        return "No medications on file."
    lines = []
    for m in active:
        desc = m.name
        if m.appearance:
            desc += f" (the {m.appearance})"
        if m.dosage:
            desc += f", {m.dosage}"
        tail = ", ".join(x for x in (m.schedule, m.instructions) if x)
        lines.append(f"- {desc}{': ' + tail if tail else ''}")
    return "\n".join(lines)


async def build_dynamic_variables(
    patient_id: str | None, direction: str = "outbound"
) -> dict[str, str]:
    """Return the EHR-derived dynamic variables for a call. Safe with no patient.

    ``direction`` ("inbound"/"outbound") lets the agent switch between running a
    check-in (outbound) and answering the patient's questions (inbound).
    """
    now = _local_now()
    variables = {
        "call_direction": direction,
        "patient_name": "",
        "procedure": "your recent procedure",
        "recovery_day": "",
        "current_time": now.strftime("%A at %-I:%M %p"),
        "medications": "No medications on file.",
        "ehr_notes": "",
    }
    if not patient_id:
        return variables

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Patient)
            .where(Patient.id == patient_id)
            .options(selectinload(Patient.medications))
        )
        p = result.scalar_one_or_none()
        if not p:
            return variables
        variables["patient_name"] = (p.name or "").split(" ")[0]
        variables["procedure"] = p.procedure or "your recent procedure"
        variables["recovery_day"] = _recovery_day(p.surgery_date)
        variables["ehr_notes"] = p.notes or ""
        variables["medications"] = _format_medications(list(p.medications))
    return variables
