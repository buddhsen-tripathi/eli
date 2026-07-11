from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.caregivers import _serialize as _serialize_caregiver
from app.database import get_db
from app.db_models import Patient
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
