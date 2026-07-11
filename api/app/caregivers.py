from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.db_models import Caregiver, Patient

router = APIRouter(prefix="/api", tags=["caregivers"])


class CaregiverIn(BaseModel):
    name: str
    relationship_to_patient: str | None = None
    phone: str | None = None
    email: str | None = None
    notify_when: str = "always"  # always | urgent | never
    is_primary: bool = False


def _serialize(c: Caregiver) -> dict:
    return {
        "id": c.id,
        "patient_id": c.patient_id,
        "name": c.name,
        "relationship_to_patient": c.relationship_to_patient,
        "phone": c.phone,
        "email": c.email,
        "notify_when": c.notify_when,
        "is_primary": c.is_primary,
    }


@router.get("/patients/{patient_id}/caregivers")
async def list_caregivers(patient_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Caregiver).where(Caregiver.patient_id == patient_id)
    )
    return [_serialize(c) for c in result.scalars().all()]


@router.post("/patients/{patient_id}/caregivers", status_code=201)
async def add_caregiver(
    patient_id: str, body: CaregiverIn, db: AsyncSession = Depends(get_db)
):
    if not await db.get(Patient, patient_id):
        raise HTTPException(status_code=404, detail="patient not found")
    caregiver = Caregiver(patient_id=patient_id, **body.model_dump())
    db.add(caregiver)
    await db.commit()
    await db.refresh(caregiver)
    return _serialize(caregiver)


@router.delete("/caregivers/{caregiver_id}", status_code=204)
async def delete_caregiver(caregiver_id: str, db: AsyncSession = Depends(get_db)):
    caregiver = await db.get(Caregiver, caregiver_id)
    if not caregiver:
        raise HTTPException(status_code=404, detail="caregiver not found")
    await db.delete(caregiver)
    await db.commit()
