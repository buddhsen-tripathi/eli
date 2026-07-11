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


@router.post("/{patient_id}")
async def start_checkin(patient_id: str, db: AsyncSession = Depends(get_db)):
    """Dial a patient and hand the answered call to the voice bridge."""
    patient = await db.get(Patient, patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="patient not found")

    base_url = os.environ["PUBLIC_BASE_URL"].rstrip("/")
    from_number = os.environ["TWILIO_PHONE_NUMBER"]
    # Pass patient_id so the bridge can link the call and notify the right loved ones.
    connected_url = f"{base_url}/call/incoming?patient_id={patient_id}"

    sid = await _place_call(patient.phone, from_number, connected_url)
    return {"call_sid": sid, "patient_id": patient_id, "status": "dialing"}
