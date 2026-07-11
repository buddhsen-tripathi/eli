from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.db_models import Call, TranscriptTurn

router = APIRouter(prefix="/api/calls", tags=["calls"])


@router.get("")
async def list_calls(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Call).order_by(Call.started_at.desc()))
    calls = result.scalars().all()
    return [
        {
            "id": c.id,
            "call_sid": c.call_sid,
            "patient_id": c.patient_id,
            "direction": c.direction,
            "status": c.status,
            "started_at": c.started_at,
            "ended_at": c.ended_at,
            "summary": c.summary,
            "triage": c.triage,
            "notified_at": c.notified_at,
        }
        for c in calls
    ]


@router.get("/{call_id}")
async def get_call(call_id: str, db: AsyncSession = Depends(get_db)):
    call = await db.get(Call, call_id)
    if not call:
        raise HTTPException(status_code=404, detail="call not found")
    return {
        "id": call.id,
        "call_sid": call.call_sid,
        "patient_id": call.patient_id,
        "direction": call.direction,
        "status": call.status,
        "started_at": call.started_at,
        "ended_at": call.ended_at,
        "summary": call.summary,
        "triage": call.triage,
        "notified_at": call.notified_at,
    }


@router.post("/{call_id}/rerun")
async def rerun_analysis(call_id: str, db: AsyncSession = Depends(get_db)):
    """Re-run analysis + caregiver notification for a call (useful for testing)."""
    from app.analysis import analyze_call
    from app.notify import notify_caregivers

    if not await db.get(Call, call_id):
        raise HTTPException(status_code=404, detail="call not found")
    triage = await analyze_call(call_id)
    await notify_caregivers(call_id)
    return {"call_id": call_id, "triage": triage}


@router.get("/{call_id}/turns")
async def get_turns(call_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(TranscriptTurn)
        .where(TranscriptTurn.call_id == call_id)
        .order_by(TranscriptTurn.timestamp)
    )
    turns = result.scalars().all()
    return [
        {"id": t.id, "role": t.role, "text": t.text, "timestamp": t.timestamp}
        for t in turns
    ]
