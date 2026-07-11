from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.db_models import Medication, Patient

router = APIRouter(prefix="/api", tags=["medications"])


class MedicationIn(BaseModel):
    name: str
    appearance: str | None = None
    tactile: str | None = None
    dosage: str | None = None
    schedule: str | None = None
    instructions: str | None = None
    purpose: str | None = None
    active: bool = True


class MedicationPatch(BaseModel):
    name: str | None = None
    appearance: str | None = None
    tactile: str | None = None
    dosage: str | None = None
    schedule: str | None = None
    instructions: str | None = None
    purpose: str | None = None
    active: bool | None = None


def serialize(m: Medication) -> dict:
    return {
        "id": m.id,
        "patient_id": m.patient_id,
        "name": m.name,
        "appearance": m.appearance,
        "tactile": m.tactile,
        "dosage": m.dosage,
        "schedule": m.schedule,
        "instructions": m.instructions,
        "purpose": m.purpose,
        "active": m.active,
    }


@router.get("/patients/{patient_id}/medications")
async def list_medications(patient_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Medication).where(Medication.patient_id == patient_id).order_by(Medication.created_at)
    )
    return [serialize(m) for m in result.scalars().all()]


@router.post("/patients/{patient_id}/medications", status_code=201)
async def add_medication(
    patient_id: str, body: MedicationIn, db: AsyncSession = Depends(get_db)
):
    if not await db.get(Patient, patient_id):
        raise HTTPException(status_code=404, detail="patient not found")
    med = Medication(patient_id=patient_id, **body.model_dump())
    db.add(med)
    await db.commit()
    await db.refresh(med)
    return serialize(med)


@router.patch("/medications/{medication_id}")
async def update_medication(
    medication_id: str, body: MedicationPatch, db: AsyncSession = Depends(get_db)
):
    med = await db.get(Medication, medication_id)
    if not med:
        raise HTTPException(status_code=404, detail="medication not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(med, field, value)
    await db.commit()
    await db.refresh(med)
    return serialize(med)


@router.delete("/medications/{medication_id}", status_code=204)
async def delete_medication(medication_id: str, db: AsyncSession = Depends(get_db)):
    med = await db.get(Medication, medication_id)
    if not med:
        raise HTTPException(status_code=404, detail="medication not found")
    await db.delete(med)
    await db.commit()
