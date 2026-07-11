"""
Notify loved ones after a check-in call.

`notify_caregivers(call_id)` loads the patient's caregivers and the call's
summary + triage, then sends an SMS to each caregiver whose `notify_when`
preference matches this call's triage level. Twilio credentials are read lazily,
so a missing config degrades to a logged no-op rather than crashing the call.

Email is left as a TODO — SMS covers the demo and reuses the Twilio account we
already have for voice.
"""

import asyncio
import os
from datetime import datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import AsyncSessionLocal
from app.db_models import Call, Caregiver, Patient


def _should_notify(notify_when: str, level: str) -> bool:
    if notify_when == "never":
        return False
    if notify_when == "urgent":
        return level == "urgent"
    return True  # "always"


def _compose_sms(patient_name: str, level: str, summary: str) -> str:
    prefix = {
        "urgent": f"⚠️ Please check on {patient_name} — their post-op call raised a concern.",
        "monitor": f"Update on {patient_name}'s post-op check-in.",
        "ok": f"{patient_name}'s post-op check-in went well.",
    }.get(level, f"Update on {patient_name}.")
    return f"{prefix}\n\n{summary}\n\n— arya care"


def _send_sms_sync(to: str, from_number: str, body: str) -> None:
    account_sid = os.environ["TWILIO_ACCOUNT_SID"]
    auth_token = os.environ["TWILIO_AUTH_TOKEN"]
    url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"
    resp = httpx.post(
        url,
        auth=(account_sid, auth_token),
        data={"To": to, "From": from_number, "Body": body},
        timeout=15.0,
    )
    resp.raise_for_status()


async def notify_caregivers(call_id: str) -> None:
    async with AsyncSessionLocal() as session:
        call = await session.get(Call, call_id)
        if not call or not call.patient_id:
            print(f"[notify] call {call_id} has no patient — skipping", flush=True)
            return

        result = await session.execute(
            select(Patient)
            .where(Patient.id == call.patient_id)
            .options(selectinload(Patient.caregivers))
        )
        patient = result.scalar_one_or_none()
        if not patient:
            return

        triage = call.triage or {"level": "ok"}
        level = triage.get("level", "ok")
        summary = call.summary or "Check-in completed."
        caregivers = list(patient.caregivers)

    from_number = os.environ.get("TWILIO_PHONE_NUMBER")
    if not (from_number and os.environ.get("TWILIO_ACCOUNT_SID")):
        print("[notify] Twilio not configured — skipping caregiver SMS", flush=True)
        return

    body = _compose_sms(patient.name, level, summary)
    sent = 0
    for cg in caregivers:
        if not cg.phone or not _should_notify(cg.notify_when, level):
            continue
        try:
            await asyncio.to_thread(_send_sms_sync, cg.phone, from_number, body)
            sent += 1
        except Exception as e:
            print(f"[notify] failed to text {cg.name}: {e}", flush=True)

    async with AsyncSessionLocal() as session:
        call = await session.get(Call, call_id)
        if call:
            call.notified_at = datetime.now(timezone.utc)
            await session.commit()

    print(f"[notify] call {call_id}: notified {sent}/{len(caregivers)} caregivers (level={level})", flush=True)
