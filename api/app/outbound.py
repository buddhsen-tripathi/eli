"""
Outbound check-in call: the agent phones a post-op patient.

Flow:
  1. POST /call/outbound/{patient_id} places a Twilio call to the patient.
  2. When they answer, Twilio hits POST /call/incoming, which returns the same
     <Connect><Stream> TwiML as an inbound call — so the existing /call/stream
     bridge (app/voice.py) handles the conversation for both directions.

Kept deliberately small: place-the-call is the only outbound-specific piece for
now. Enrich the TwiML / agent prompt with patient context when the idea firms up.
"""

import asyncio
import os

import httpx
from fastapi import APIRouter, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Depends

from app.database import get_db
from app.db_models import Patient

router = APIRouter(prefix="/call/outbound", tags=["outbound"])


def _twilio_credentials() -> tuple[str, str]:
    return os.environ["TWILIO_ACCOUNT_SID"], os.environ["TWILIO_AUTH_TOKEN"]


def _place_call_sync(to: str, from_number: str, connected_url: str) -> str:
    """Place an outbound call via the Twilio REST API. Returns the call SID."""
    account_sid, auth_token = _twilio_credentials()
    url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Calls.json"
    resp = httpx.post(
        url,
        auth=(account_sid, auth_token),
        data={"To": to, "From": from_number, "Url": connected_url, "Method": "POST"},
        timeout=15.0,
    )
    resp.raise_for_status()
    return resp.json()["sid"]


async def _place_call(to: str, from_number: str, connected_url: str) -> str:
    return await asyncio.to_thread(_place_call_sync, to, from_number, connected_url)


@router.post("")
async def demo_checkin(db: AsyncSession = Depends(get_db)):
    """Demo/smoke test: create a patient from DESTINATION_PHONE_NUMBER and dial it.

    Lets us place a real check-in call without pre-seeding the DB — the number is
    read from the server env, never sent over the wire.
    """
    to = os.environ.get("DESTINATION_PHONE_NUMBER")
    if not to:
        raise HTTPException(status_code=400, detail="DESTINATION_PHONE_NUMBER not set")

    patient = Patient(name="Demo Patient", phone=to, procedure="knee replacement surgery")
    db.add(patient)
    await db.commit()
    await db.refresh(patient)

    base_url = os.environ["PUBLIC_BASE_URL"].rstrip("/")
    from_number = os.environ["TWILIO_PHONE_NUMBER"]
    connected_url = f"{base_url}/call/incoming?patient_id={patient.id}"

    try:
        sid = await _place_call(to, from_number, connected_url)
    except httpx.HTTPStatusError as e:
        # Surface Twilio's error body (e.g. unverified number, geo perms) verbatim.
        raise HTTPException(status_code=502, detail=f"Twilio error: {e.response.text}")

    return {"call_sid": sid, "patient_id": patient.id, "to": to, "status": "dialing"}


@router.post("/{patient_id}")
async def start_checkin(
    patient_id: str, day: int | None = None, db: AsyncSession = Depends(get_db)
):
    """Dial a patient and hand the answered call to the voice bridge.

    Optional ``day`` overrides the recovery day the agent is told (otherwise it's
    computed from the surgery date) — handy for demoing a specific post-op day.
    """
    patient = await db.get(Patient, patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="patient not found")

    base_url = os.environ["PUBLIC_BASE_URL"].rstrip("/")
    from_number = os.environ["TWILIO_PHONE_NUMBER"]
    # Pass patient_id so the bridge can link the call and notify the right loved ones.
    connected_url = f"{base_url}/call/incoming?patient_id={patient_id}"
    if day is not None:
        connected_url += f"&day={day}"

    sid = await _place_call(patient.phone, from_number, connected_url)
    return {"call_sid": sid, "patient_id": patient_id, "day": day, "status": "dialing"}
