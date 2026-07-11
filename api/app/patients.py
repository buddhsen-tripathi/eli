import os
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.caregivers import _serialize as _serialize_caregiver
from app.database import get_db
from app.db_models import Caregiver, Medication, Patient
from app.medications import serialize as _serialize_medication

router = APIRouter(prefix="/api/patients", tags=["patients"])


class PatientIn(BaseModel):
    name: str
    phone: str
    procedure: str | None = None
    surgery_date: date | None = None
    clinician: str | None = None
    notes: str | None = None
    checkin_days: list[int] | None = None


class PatientPatch(BaseModel):
    name: str | None = None
    phone: str | None = None
    procedure: str | None = None
    surgery_date: date | None = None
    clinician: str | None = None
    notes: str | None = None
    checkin_days: list[int] | None = None


def _serialize(p: Patient) -> dict:
    return {
        "id": p.id,
        "name": p.name,
        "phone": p.phone,
        "procedure": p.procedure,
        "surgery_date": p.surgery_date,
        "clinician": p.clinician,
        "notes": p.notes,
        "checkin_days": p.checkin_days,
        "created_at": p.created_at,
    }


@router.get("")
async def list_patients(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Patient).order_by(Patient.created_at.desc()))
    return [_serialize(p) for p in result.scalars().all()]


DEMO_NAME = "Margaret Chen"


@router.post("/demo-seed", status_code=201)
async def seed_demo_patient(db: AsyncSession = Depends(get_db)):
    """Create (or refresh) a rich demo patient using DESTINATION_PHONE_NUMBER.

    The phone is read from the server env so the number never travels over the
    wire. Idempotent — replaces any prior demo record. Built for the live demo:
    the med appearances drive the "which is my red pill?" scenario.
    """
    phone = os.environ.get("DESTINATION_PHONE_NUMBER")
    if not phone:
        raise HTTPException(status_code=400, detail="DESTINATION_PHONE_NUMBER not set")
    if not phone.startswith("+"):
        phone = "+" + phone

    # Remove any prior demo patient (cascade clears its meds + caregivers).
    old = await db.execute(select(Patient.id).where(Patient.name == DEMO_NAME))
    old_ids = [row[0] for row in old]
    if old_ids:
        await db.execute(delete(Patient).where(Patient.id.in_(old_ids)))
        await db.commit()

    patient = Patient(
        name=DEMO_NAME,
        phone=phone,
        procedure="right total hip replacement",
        surgery_date=date.today() - timedelta(days=3),
        clinician="Dr. Alvarez",
        checkin_days=[1, 3, 7],
        notes=(
            "• Discharged 3 days ago after right total hip replacement.\n"
            "• Lives alone; daughter Sarah visits on weekends.\n"
            "• Watch for infection at the incision (redness, warmth, drainage) and fall risk.\n"
            "• History of mild, well-controlled hypertension.\n"
            "• Independent with a walker at discharge."
        ),
    )
    patient.medications = [
        Medication(name="Amoxicillin", appearance="small red capsule", dosage="500mg, 1 capsule",
                   schedule="8:00 AM and 8:00 PM", instructions="with food", purpose="prevents infection"),
        Medication(name="Oxycodone", appearance="white oval tablet", dosage="5mg, 1 tablet",
                   schedule="every 6 hours as needed", instructions="for pain, take with food", purpose="pain relief"),
        Medication(name="Aspirin", appearance="small round white pill", dosage="81mg, 1 tablet",
                   schedule="9:00 AM", instructions="with water", purpose="blood thinner to prevent clots"),
    ]
    patient.caregivers = [
        Caregiver(name="Sarah Chen", relationship_to_patient="daughter", phone=phone,
                  notify_when="always", is_primary=True),
    ]
    db.add(patient)
    await db.commit()
    await db.refresh(patient)
    return {"id": patient.id, "name": patient.name, "phone": patient.phone, "status": "seeded"}


@router.post("", status_code=201)
async def create_patient(body: PatientIn, db: AsyncSession = Depends(get_db)):
    patient = Patient(**body.model_dump(exclude_none=True))
    db.add(patient)
    await db.commit()
    await db.refresh(patient)
    return _serialize(patient)


@router.get("/{patient_id}")
async def get_patient(patient_id: str, db: AsyncSession = Depends(get_db)):
    patient = await db.get(Patient, patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="patient not found")
    return _serialize(patient)


@router.get("/{patient_id}/detail")
async def get_patient_detail(patient_id: str, db: AsyncSession = Depends(get_db)):
    """Full EHR for the detail page: patient + medications + caregivers + calls."""
    result = await db.execute(
        select(Patient)
        .where(Patient.id == patient_id)
        .options(
            selectinload(Patient.medications),
            selectinload(Patient.caregivers),
            selectinload(Patient.calls),
        )
    )
    patient = result.scalar_one_or_none()
    if not patient:
        raise HTTPException(status_code=404, detail="patient not found")
    return {
        **_serialize(patient),
        "medications": [_serialize_medication(m) for m in patient.medications],
        "caregivers": [_serialize_caregiver(c) for c in patient.caregivers],
        "calls": [
            {
                "id": c.id,
                "direction": c.direction,
                "status": c.status,
                "started_at": c.started_at,
                "ended_at": c.ended_at,
                "summary": c.summary,
                "triage": c.triage,
                "notified_at": c.notified_at,
            }
            for c in patient.calls
        ],
    }


@router.patch("/{patient_id}")
async def update_patient(
    patient_id: str, body: PatientPatch, db: AsyncSession = Depends(get_db)
):
    patient = await db.get(Patient, patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="patient not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(patient, field, value)
    await db.commit()
    await db.refresh(patient)
    return _serialize(patient)
