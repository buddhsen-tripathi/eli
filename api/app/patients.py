from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.db_models import Patient

router = APIRouter(prefix="/api/patients", tags=["patients"])


class PatientIn(BaseModel):
    name: str
    phone: str
    procedure: str | None = None
    surgery_date: date | None = None
    clinician: str | None = None
    notes: str | None = None


def _serialize(p: Patient) -> dict:
    return {
        "id": p.id,
        "name": p.name,
        "phone": p.phone,
        "procedure": p.procedure,
        "surgery_date": p.surgery_date,
        "clinician": p.clinician,
        "notes": p.notes,
        "created_at": p.created_at,
    }


@router.get("")
async def list_patients(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Patient).order_by(Patient.created_at.desc()))
    return [_serialize(p) for p in result.scalars().all()]


@router.post("", status_code=201)
async def create_patient(body: PatientIn, db: AsyncSession = Depends(get_db)):
    patient = Patient(**body.model_dump())
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
