import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Patient(Base):
    """A post-op patient — typically an elderly, recently-discharged person the
    agent checks in on, who may live alone."""

    __tablename__ = "patients"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String)
    phone: Mapped[str] = mapped_column(String, index=True)
    procedure: Mapped[str | None] = mapped_column(String, nullable=True)
    surgery_date: Mapped[datetime | None] = mapped_column(Date, nullable=True)
    # Owning clinician (free-form for now; swap for a users table when auth lands).
    clinician: Mapped[str | None] = mapped_column(String, nullable=True)
    # The EHR narrative — the doctor's bullet-point notes. This is the source of
    # truth the agent is given as context on every call.
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Post-op days to place a check-in on (relative to surgery_date). The demo
    # triggers calls with a button; this drives scheduling later.
    checkin_days: Mapped[list | None] = mapped_column(JSONB, default=lambda: [1, 3, 7])
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    caregivers: Mapped[list["Caregiver"]] = relationship(
        back_populates="patient", cascade="all, delete-orphan"
    )
    medications: Mapped[list["Medication"]] = relationship(
        back_populates="patient", cascade="all, delete-orphan"
    )
    calls: Mapped[list["Call"]] = relationship(
        back_populates="patient", order_by="Call.started_at.desc()"
    )


class Medication(Base):
    """A prescription in the patient's EHR. The ``appearance`` field is the key
    to the whole product — elderly patients identify pills by look ("the small
    red one"), not by name, so the agent is given it to map cues to schedules."""

    __tablename__ = "medications"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    patient_id: Mapped[str] = mapped_column(String, ForeignKey("patients.id"), index=True)
    name: Mapped[str] = mapped_column(String)  # "Amoxicillin"
    appearance: Mapped[str | None] = mapped_column(String, nullable=True)  # "small red capsule"
    # Tactile cue for low-vision patients: how the pill feels — shape, size,
    # score lines, coating. e.g. "round with a line you can feel across the middle".
    tactile: Mapped[str | None] = mapped_column(String, nullable=True)
    dosage: Mapped[str | None] = mapped_column(String, nullable=True)  # "500mg, 1 tablet"
    schedule: Mapped[str | None] = mapped_column(String, nullable=True)  # "8:00 AM and 8:00 PM"
    instructions: Mapped[str | None] = mapped_column(String, nullable=True)  # "with food"
    purpose: Mapped[str | None] = mapped_column(String, nullable=True)  # "for infection"
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    patient: Mapped["Patient"] = relationship(back_populates="medications")


class Caregiver(Base):
    """A loved one / emergency contact notified after a check-in call."""

    __tablename__ = "caregivers"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    patient_id: Mapped[str] = mapped_column(String, ForeignKey("patients.id"), index=True)
    name: Mapped[str] = mapped_column(String)
    relationship_to_patient: Mapped[str | None] = mapped_column(String, nullable=True)  # daughter, son, neighbor…
    phone: Mapped[str | None] = mapped_column(String, nullable=True)
    email: Mapped[str | None] = mapped_column(String, nullable=True)
    # When to reach out: "always" after every call, or "urgent" only on concerning triage.
    notify_when: Mapped[str] = mapped_column(String, default="always")  # always | urgent | never
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)

    patient: Mapped["Patient"] = relationship(back_populates="caregivers")


class Call(Base):
    __tablename__ = "calls"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    call_sid: Mapped[str] = mapped_column(String, unique=True, index=True)
    patient_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("patients.id"), index=True, nullable=True
    )
    direction: Mapped[str] = mapped_column(String, default="inbound")  # inbound | outbound
    status: Mapped[str] = mapped_column(String, default="in_progress")  # in_progress | completed | failed
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # ElevenLabs conversation id — used to pull the authoritative transcript post-call.
    el_conversation_id: Mapped[str | None] = mapped_column(String, nullable=True)

    # Post-call analysis produced from the transcript (see app/analysis.py):
    #   summary: short plain-language recap for a loved one
    #   triage:  {"level": "ok|monitor|urgent", "flags": [...], "reason": "..."}
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    triage: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # Whether loved ones have been notified about this call yet.
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    patient: Mapped["Patient | None"] = relationship(back_populates="calls")
    turns: Mapped[list["TranscriptTurn"]] = relationship(
        back_populates="call", order_by="TranscriptTurn.timestamp"
    )


class TranscriptTurn(Base):
    __tablename__ = "transcript_turns"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    call_id: Mapped[str] = mapped_column(String, ForeignKey("calls.id"), index=True)
    role: Mapped[str] = mapped_column(String)  # agent | patient
    text: Mapped[str] = mapped_column(Text)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    call: Mapped["Call"] = relationship(back_populates="turns")
